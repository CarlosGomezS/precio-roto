# Precio Roto · detector de errores de precio

## Qué hay en la carpeta

| Archivo | Para qué sirve |
|---|---|
| `detector.py` | El script. Lee los catálogos de las tiendas, guarda el historial de precios y detecta los errores. |
| `config.json` | Las tiendas que vigilas y los umbrales de detección. |
| `index.html` | La web. Lee `deals.json` y muestra las alertas. |
| `demo.py` | Simula unos días de precios y unos errores para probarlo sin conectar ninguna tienda. |
| `deals.json` | Lo genera el detector: las alertas que se ven en la web. |
| `precios.db` | Lo genera el detector: el historial de precios (SQLite). |

Solo necesitas Python 3.9 o posterior. No hay que instalar nada más.

## Probarlo ahora

```bash
python demo.py
```

Verás en pantalla las alertas que detecta, y en `demo_deals.json` lo que mostraría la web. La demo usa sus propios archivos y no toca los datos reales.

## Cómo detecta un error

Para cada producto, el script calcula el **precio habitual**, que es la mediana de sus precios de los últimos 14 días. Hay alerta cuando se cumplen estas cuatro condiciones:

- El precio actual está al menos un **50 %** por debajo del habitual.
- El precio habitual es de **15 € o más**, para no llenarse de avisos de cosas baratas.
- Hay al menos **3 lecturas** previas, porque sin historial no hay con qué comparar.
- No se avisó de ese producto en las últimas 24 h, salvo que el precio haya bajado todavía más.

Todos estos valores se cambian en la sección `thresholds` de `config.json`.

## Conectar tiendas reales

1. Date de alta como afiliado en **Awin** (awin.com/es). Hazlo también en Tradedoubler o Admitad si alguna tienda que te interesa está allí.
2. Solicita unirte al programa de cada tienda. Cada una aprueba o rechaza tu solicitud.
3. En Awin, ve a *Toolbox → Create-a-Feed*, elige la tienda y las columnas `aw_product_id, product_name, search_price, aw_deep_link, merchant_image_url, in_stock`, y copia la URL de descarga.
4. Pega esa URL en `source` dentro de `config.json` y pon `"enabled": true`.
5. Borra los feeds de ejemplo y `precios.db`.

Los enlaces `aw_deep_link` ya llevan tu código de afiliado, así que cobras comisión por cada venta.

Si una tienda usa otros nombres de columna, cambia los nombres dentro de `columns`.

## Telegram

1. Habla con **@BotFather** en Telegram, usa `/newbot` y guarda el token que te da.
2. Crea un canal y añade el bot como administrador.
3. Antes de lanzar el script, define estas dos variables:

```bash
export TELEGRAM_TOKEN="123456:ABC..."
export TELEGRAM_CHAT_ID="@nombre_de_tu_canal"
```

Si no las defines, o si usas `--dry-run`, las alertas solo se escriben en pantalla.

## Publicarlo gratis con GitHub

Con esto, la web y el detector funcionan solos, sin servidor y sin pagar nada.

1. Crea una cuenta en github.com y un repositorio **público** nuevo, por ejemplo `precio-roto`.
2. Sube todo el contenido de esta carpeta, incluida la carpeta oculta `.github`.
3. Ve a *Settings → Pages*. En *Source* elige `Deploy from a branch`, después la rama `main` y la carpeta `/ (root)`, y guarda. Tu web estará en `https://TU_USUARIO.github.io/precio-roto/`.
4. Ve a *Settings → Secrets and variables → Actions* y crea dos secretos: `TELEGRAM_TOKEN` y `TELEGRAM_CHAT_ID`.
5. Ve a *Actions*, abre «Detector de errores de precio» y pulsa *Run workflow* para probarlo. A partir de ahí se ejecuta solo cada 15 minutos.

Para usar un dominio propio, como `precioroto.es` (unos 10 € al año), configúralo en *Settings → Pages → Custom domain*.

Si lo prefieres a mano, también puedes ejecutarlo así:

## Dejarlo funcionando

```bash
python detector.py --loop 600     # una pasada cada 10 minutos
```

Ojo: los feeds de afiliación suelen actualizarse cada pocas horas, no al minuto. Bajar de 10 minutos no te dará alertas antes y puede hacer que la red te limite.

Para tenerlo encendido las 24 horas sin pagar casi nada:
- **Un VPS barato** con `cron`: `*/10 * * * * cd /ruta/precio-roto && python3 detector.py`.
- **La web**: sube `index.html` y `deals.json` a cualquier hosting estático. Si el detector corre en el mismo servidor, la web se actualiza sola.

## Antes de publicar

- Pon el aviso de afiliado (ya está en el pie de la web) y una página de política de cookies si usas AdSense.
- Un error de precio no obliga a la tienda a vender. Dilo claro para no tener quejas.
- Revisa las condiciones de cada programa de afiliados. Algunos no permiten anunciar en Telegram o exigen aprobación previa.
