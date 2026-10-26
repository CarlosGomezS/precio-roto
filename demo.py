#!/usr/bin/env python3
"""
Demo: simula 5 días de precios normales y luego mete errores de precio en los
feeds de ejemplo, para ver el detector funcionando sin conectar ninguna tienda.

  python demo.py
"""
import csv
import os
import random

import detector

BASE = os.path.dirname(os.path.abspath(__file__))
FEEDS = {
    "feeds/ejemplo_pccomponentes.csv": [
        ("pcc-1", "Monitor gaming 27\" QHD 165 Hz", 329.0),
        ("pcc-2", "Disco SSD NVMe 2 TB", 159.0),
        ("pcc-3", "Teclado mecánico", 119.0),
        ("pcc-4", "Ratón inalámbrico", 49.0),
        ("pcc-5", "Cable HDMI 2 m", 9.99),
    ],
    "feeds/ejemplo_mediamarkt.csv": [
        ("mm-1", "Televisor 55\" 4K", 699.0),
        ("mm-2", "Auriculares con cancelación de ruido", 279.0),
        ("mm-3", "Cafetera superautomática", 649.0),
        ("mm-4", "Freidora de aire 6 L", 129.0),
    ],
}
# Errores que aparecerán en la última pasada (precio final)
ERRORS = {"pcc-1": 32.90, "mm-2": 89.0, "pcc-5": 0.99, "mm-4": 99.0}
HEADER = ["aw_product_id", "product_name", "search_price", "aw_deep_link", "merchant_image_url", "in_stock"]


def write_feed(path, products, prices):
    os.makedirs(os.path.join(BASE, "feeds"), exist_ok=True)
    with open(os.path.join(BASE, path), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(HEADER)
        for pid, name, _ in products:
            w.writerow([pid, name, f"{prices[pid]:.2f}", f"https://ejemplo.com/p/{pid}", "", "1"])


def main():
    cfg = detector.load_config(os.path.join(BASE, "config.json"))
    # La demo usa sus propios archivos para no mezclarse con los datos reales
    cfg["db_path"] = "demo.db"
    cfg["output_json"] = "demo_deals.json"
    cfg["feeds"] = [dict(f, enabled=True) for f in cfg["feeds"] if f.get("source", "").startswith("feeds/ejemplo_")]
    db_path = os.path.join(BASE, cfg["db_path"])
    if os.path.exists(db_path):
        os.remove(db_path)

    random.seed(7)
    import time
    start = int(time.time()) - 5 * 86400
    print("== Simulando 5 días de precios normales ==")
    for day in range(5):
        for path, products in FEEDS.items():
            prices = {pid: base * random.uniform(0.95, 1.03) for pid, _, base in products}
            write_feed(path, products, prices)
        detector.run_once(cfg, dry_run=True, now=start + day * 86400)

    print("\n== Hoy: aparecen errores de precio ==")
    for path, products in FEEDS.items():
        prices = {pid: ERRORS.get(pid, base) for pid, _, base in products}
        write_feed(path, products, prices)
    detector.run_once(cfg, dry_run=True)
    print("\nAbre demo_deals.json para ver lo que mostraría la web.")


if __name__ == "__main__":
    main()
