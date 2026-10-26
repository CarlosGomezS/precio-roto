#!/usr/bin/env python3
"""
Precio Roto · detector de errores de precio
-------------------------------------------
Lee los catálogos de producto (feeds) de las tiendas, guarda el historial de
precios en SQLite, detecta bajadas anómalas y:
  1) escribe deals.json para la web,
  2) envía cada alerta nueva a un canal de Telegram.

Solo usa la biblioteca estándar de Python 3.9+.

Uso:
  python detector.py                 # una pasada
  python detector.py --loop 300      # repetir cada 300 s
  python detector.py --dry-run       # no envía nada a Telegram
"""
import argparse
import csv
import gzip
import io
import json
import os
import sqlite3
import statistics
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

BASE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE, "config.json")


# ---------------------------------------------------------------- utilidades
def log(msg):
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def load_config(path):
    with open(path, encoding="utf-8") as f:
        cfg = json.load(f)
    cfg.setdefault("thresholds", {})
    t = cfg["thresholds"]
    t.setdefault("min_drop_pct", 50)        # bajada mínima respecto al precio habitual
    t.setdefault("min_ref_price", 15)       # ignora productos baratos (ruido)
    t.setdefault("min_history", 3)          # lecturas previas necesarias
    t.setdefault("history_days", 14)        # ventana para el precio habitual
    t.setdefault("realert_hours", 24)       # no repetir alerta del mismo producto
    t.setdefault("deal_ttl_hours", 48)      # cuánto tiempo sale una alerta en la web
    cfg.setdefault("db_path", "precios.db")
    cfg.setdefault("output_json", "deals.json")
    return cfg


def to_float(value):
    """Convierte '1.299,00', '1299.00', '59,99 €' en float. None si no puede."""
    if value is None:
        return None
    s = str(value).strip().replace("€", "").replace("EUR", "").replace(" ", "")
    if not s:
        return None
    if "," in s and "." in s:
        # el separador que aparece al final es el decimal
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def to_bool(value):
    if value is None or value == "":
        return True  # si el feed no lo dice, suponemos que hay stock
    return str(value).strip().lower() in ("1", "true", "yes", "si", "sí", "in stock", "instock")


# -------------------------------------------------------------- lectura feed
def read_feed(feed):
    """Devuelve una lista de dicts normalizados: id, name, price, url, stock, image."""
    src = feed["source"]
    if src.startswith(("http://", "https://")):
        req = urllib.request.Request(src, headers={"User-Agent": "PrecioRoto/1.0"})
        with urllib.request.urlopen(req, timeout=120) as r:
            raw = r.read()
    else:
        path = src if os.path.isabs(src) else os.path.join(BASE, src)
        with open(path, "rb") as f:
            raw = f.read()

    if raw[:2] == b"\x1f\x8b":  # gzip (habitual en Awin)
        raw = gzip.decompress(raw)

    text = raw.decode(feed.get("encoding", "utf-8"), errors="replace")
    delim = feed.get("delimiter") or csv.Sniffer().sniff(text[:5000], delimiters=",;|\t").delimiter
    cols = feed["columns"]
    items = []
    for row in csv.DictReader(io.StringIO(text), delimiter=delim):
        price = to_float(row.get(cols["price"]))
        pid = (row.get(cols["id"]) or "").strip()
        if not pid or price is None or price <= 0:
            continue
        items.append({
            "id": pid,
            "name": (row.get(cols["name"]) or "").strip(),
            "price": price,
            "url": (row.get(cols.get("url", ""), "") or "").strip(),
            "image": (row.get(cols.get("image", ""), "") or "").strip(),
            "stock": to_bool(row.get(cols.get("stock", ""))),
        })
    return items


# -------------------------------------------------------------- base de datos
SCHEMA = """
CREATE TABLE IF NOT EXISTS prices (
  store TEXT, product_id TEXT, price REAL, ts INTEGER
);
CREATE INDEX IF NOT EXISTS ix_prices ON prices(store, product_id, ts);
CREATE TABLE IF NOT EXISTS products (
  store TEXT, product_id TEXT, name TEXT, url TEXT, image TEXT,
  last_price REAL, last_stock INTEGER, last_seen INTEGER,
  PRIMARY KEY (store, product_id)
);
CREATE TABLE IF NOT EXISTS alerts (
  store TEXT, product_id TEXT, price REAL, ref_price REAL, pct INTEGER, ts INTEGER
);
CREATE INDEX IF NOT EXISTS ix_alerts ON alerts(store, product_id, ts);
"""


def open_db(path):
    db = sqlite3.connect(path if os.path.isabs(path) else os.path.join(BASE, path))
    db.executescript(SCHEMA)
    return db


def reference_price(db, store, pid, since_ts, min_history):
    """Mediana de los precios previos en la ventana. None si hay poco historial."""
    rows = db.execute(
        "SELECT price FROM prices WHERE store=? AND product_id=? AND ts>=? ORDER BY ts",
        (store, pid, since_ts),
    ).fetchall()
    prices = [r[0] for r in rows]
    if len(prices) < min_history:
        return None
    return statistics.median(prices)


def recently_alerted(db, store, pid, price, since_ts):
    """True si ya avisamos de este producto hace poco a un precio igual o menor."""
    row = db.execute(
        "SELECT MIN(price) FROM alerts WHERE store=? AND product_id=? AND ts>=?",
        (store, pid, since_ts),
    ).fetchone()
    return row[0] is not None and price >= row[0] - 0.005


# --------------------------------------------------------------- detección
def process_feed(db, feed, cfg, now):
    t = cfg["thresholds"]
    store = feed["store"]
    since_hist = now - t["history_days"] * 86400
    since_alert = now - t["realert_hours"] * 3600
    new_alerts = []

    items = read_feed(feed)
    for it in items:
        ref = reference_price(db, store, it["id"], since_hist, t["min_history"])

        # 1) comparar ANTES de guardar el precio nuevo
        if ref and ref >= t["min_ref_price"] and it["stock"]:
            pct = round((1 - it["price"] / ref) * 100)
            if pct >= t["min_drop_pct"] and not recently_alerted(db, store, it["id"], it["price"], since_alert):
                db.execute(
                    "INSERT INTO alerts VALUES (?,?,?,?,?,?)",
                    (store, it["id"], it["price"], ref, pct, now),
                )
                new_alerts.append({**it, "store": store, "ref": ref, "pct": pct})

        # 2) guardar lectura y ficha del producto
        db.execute("INSERT INTO prices VALUES (?,?,?,?)", (store, it["id"], it["price"], now))
        db.execute(
            """INSERT INTO products VALUES (?,?,?,?,?,?,?,?)
               ON CONFLICT(store, product_id) DO UPDATE SET
                 name=excluded.name, url=excluded.url, image=excluded.image,
                 last_price=excluded.last_price, last_stock=excluded.last_stock,
                 last_seen=excluded.last_seen""",
            (store, it["id"], it["name"], it["url"], it["image"], it["price"], int(it["stock"]), now),
        )
    db.commit()
    return len(items), new_alerts


# ------------------------------------------------------------------ salidas
def stock_state(db_row, alert_price):
    last_price, last_stock = db_row
    if not last_stock:
        return "off"
    if last_price > alert_price * 1.05:  # ya han corregido el precio
        return "off"
    return "on"


def export_json(db, cfg, now):
    """Escribe deals.json con el formato que usa la web."""
    ttl = now - cfg["thresholds"]["deal_ttl_hours"] * 3600
    rows = db.execute(
        """SELECT a.store, a.product_id, a.price, a.ref_price, a.pct, a.ts,
                  p.name, p.url, p.image, p.last_price, p.last_stock
           FROM alerts a JOIN products p USING (store, product_id)
           WHERE a.ts >= ? ORDER BY a.ts DESC""",
        (ttl,),
    ).fetchall()
    seen, deals = set(), []
    for store, pid, price, ref, pct, ts, name, url, image, last_price, last_stock in rows:
        if (store, pid) in seen:
            continue
        seen.add((store, pid))
        deals.append({
            "s": store, "n": name, "was": round(ref, 2), "p": round(price, 2), "pct": pct,
            "at": ts * 1000, "st": stock_state((last_price, last_stock), price),
            "url": url, "img": image,
        })
    out = cfg["output_json"]
    out = out if os.path.isabs(out) else os.path.join(BASE, out)
    try:
        with open(out, encoding="utf-8") as f:
            if json.load(f).get("deals") == deals:
                return len(deals)  # sin cambios: no tocar el archivo (evita commits vacíos)
    except (OSError, ValueError):
        pass
    tmp = out + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"updated": now * 1000, "deals": deals}, f, ensure_ascii=False, indent=1)
    os.replace(tmp, out)
    return len(deals)


def eur(v):
    return f"{v:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")


def send_telegram(alert, dry_run):
    token = os.environ.get("TELEGRAM_TOKEN")
    chat = os.environ.get("TELEGRAM_CHAT_ID")
    text = (
        f"🚨 <b>ERROR DE PRECIO −{alert['pct']}%</b>\n"
        f"{alert['store']} · {alert['name']}\n\n"
        f"<s>{eur(alert['ref'])}</s> → <b>{eur(alert['price'])}</b>\n"
        f"{alert['url']}"
    )
    if dry_run or not token or not chat:
        log("  (Telegram desactivado) " + text.replace("\n", " | "))
        return
    data = urllib.parse.urlencode({
        "chat_id": chat, "text": text, "parse_mode": "HTML", "disable_web_page_preview": "false",
    }).encode()
    try:
        urllib.request.urlopen(f"https://api.telegram.org/bot{token}/sendMessage", data=data, timeout=20)
    except Exception as e:  # una alerta fallida no debe parar el resto
        log(f"  Telegram falló: {e}")


# ------------------------------------------------------------------- bucle
def run_once(cfg, dry_run, now=None):
    now = int(now or time.time())
    db = open_db(cfg["db_path"])
    total_alerts = 0
    for feed in cfg["feeds"]:
        if not feed.get("enabled", True):
            continue
        try:
            n, alerts = process_feed(db, feed, cfg, now)
            log(f"{feed['store']}: {n} productos, {len(alerts)} alertas nuevas")
            for a in alerts:
                send_telegram(a, dry_run)
            total_alerts += len(alerts)
        except Exception as e:
            log(f"{feed['store']}: ERROR al leer el feed → {e}")
    shown = export_json(db, cfg, now)
    db.close()
    log(f"Hecho. {total_alerts} alertas nuevas, {shown} en la web.")
    return total_alerts


def main():
    ap = argparse.ArgumentParser(description="Detector de errores de precio")
    ap.add_argument("--config", default=CONFIG_PATH)
    ap.add_argument("--loop", type=int, default=0, help="segundos entre pasadas (0 = una sola)")
    ap.add_argument("--dry-run", action="store_true", help="no enviar a Telegram")
    args = ap.parse_args()

    cfg = load_config(args.config)
    if not args.loop:
        run_once(cfg, args.dry_run)
        return
    log(f"Modo continuo: una pasada cada {args.loop} s. Ctrl+C para parar.")
    while True:
        start = time.time()
        run_once(cfg, args.dry_run)
        time.sleep(max(5, args.loop - (time.time() - start)))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
