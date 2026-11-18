# OFS → BingX + Telegram

Bot que recibe los paquetes JSON del indicador **Order Flow Strategy** (TradingView), los valida con las reglas de la estrategia, **envía señales detalladas a Telegram** y, si lo activas, **opera en BingX** (futuros perpetuos).

```
TradingView (indicador en 5m, alert() → JSON)
        │  webhook HTTPS  ?secret=…
        ▼
   Railway (FastAPI)  ── reglas de riesgo ──►  BingX (mercado + stop + objetivo, stop dinámico)
        │
        └──────────────────────────────────►  Telegram (señal en 4 pasos, avisos y cierres)
```

> ⚠️ **Aviso**: esto es software de automatización, no asesoramiento financiero. El trading con apalancamiento puede hacerte perder más de lo previsto. Empieza en `signals`, luego `demo`, y solo después `live` con poco capital.

## Modos (`TRADING_MODE`)

| Modo | Qué hace |
|---|---|
| `signals` (por defecto) | Solo manda mensajes a Telegram. No toca BingX. |
| `demo` | Opera en BingX **VST** (saldo virtual) con la misma lógica que el real. |
| `live` | Opera con dinero real. |

## Qué hace con cada evento del indicador

| Evento | Acción |
|---|---|
| `ABSORPTION` | Aviso informativo (quién fue agresivo, dónde se negoció el volumen, si hubo resultado). **No es entrada.** |
| `LONG_ENTRY` / `SHORT_ENTRY` | Comprueba estructura alineada, ventana, participación, R:R mínimo, límites diarios y deslizamiento. Si todo cuadra: calcula tamaño, abre a mercado, coloca **stop y objetivo** y manda la señal en 4 pasos. Si no, manda "señal descartada" con los motivos. |
| `TRADE_UPDATE` (`VALUE_RECLAIMED`, `STOP_AT_ENTRY`, `NO_RECLAIM_STOP_AT_ENTRY`, `TRAILING`) | Avisa y **mueve el stop en BingX** al valor del indicador (solo a favor, nunca hacia atrás). El stop nuevo se crea *antes* de cancelar el viejo. |
| `TRADE_UPDATE` (`TARGET_HIT`, `STOPPED`, `BREAKEVEN`, `TRAIL_STOP`) | Cancela órdenes pendientes, comprueba que la posición esté cerrada (si no, la cierra a mercado), calcula el resultado en R (estimado) y actualiza los contadores del día. |

Tamaño: `(equity × RISK_PCT%) / |entrada − stop|`, limitado por `MAX_LEVERAGE` y redondeado hacia abajo a la precisión del contrato. Si el stop no se puede colocar, **la posición se cierra** (nunca queda sin protección).

## Puesta en marcha

### 1) TradingView
1. Abre el Pine Editor, pega `OFS_Indicador_ES.pine` y pulsa *Añadir al gráfico*.
2. Gráfico **BINGX:BTCUSDT.P** en **5 minutos**. Por defecto la ventana es 24/7 (ajústalo en *Trade window* si quieres solo ciertas horas).
3. Crea una alerta sobre el indicador: **Condición → OFS-ES → "Any alert() function call"**, activa **Webhook URL** y pon:
   `https://TU-APP.up.railway.app/webhook?secret=TU_WEBHOOK_SECRET`
   (el cuerpo del mensaje se ignora: el indicador envía el JSON).
4. Requisitos de TradingView: plan de pago y 2FA activado para usar webhooks. Una alerta por símbolo.
5. En el indicador, *Send JSON packet* = "Setups and trade updates" (por defecto).

`OFS_Estrategia_Backtest_ES.pine` es la misma lógica como `strategy()` para ver estadísticas en el *Strategy Tester* (no genera alertas de webhook).

### 2) Telegram
1. En Telegram habla con **@BotFather** → `/newbot` → copia el token.
2. Escribe cualquier mensaje a tu bot y abre `https://api.telegram.org/bot<TOKEN>/getUpdates`: tu `chat.id` aparece ahí (para un grupo, añade el bot y usa el id del grupo, que empieza por `-`).

### 3) BingX (solo demo/live)
1. *API Management* → crea una API key con permisos **Lectura** y **Trading de futuros**. **Nunca** actives retiros.
2. Si puedes, restringe por IP (Railway no ofrece IP estática en todos los planes; si no la tienes, mantén los permisos mínimos y el capital bajo).
3. Modo de posición: BingX usa **hedge** por defecto (`POSITION_MODE=hedge`). Si tu cuenta está en *one-way*, pon `oneway`.
4. Para `demo` necesitas la cuenta de trading demo (VST) de BingX y la API key correspondiente.

### 4) GitHub
```bash
git init && git add . && git commit -m "OFS bot"
git branch -M main
git remote add origin https://github.com/TU_USUARIO/ofs-bingx-bot.git
git push -u origin main
```
(`.env` y `state.json` están en `.gitignore`: tus claves no se suben. Usa un repositorio **privado**.)

### 5) Railway
1. *New Project → Deploy from GitHub repo* y elige el repositorio (usa el `Dockerfile` de la raíz).
2. En *Variables* copia lo de `.env.example` (mínimo: `WEBHOOK_SECRET`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`).
3. *Settings → Networking → Generate Domain* para obtener la URL pública.
4. Añade un **Volume** montado en `/data` y pon `DATA_DIR=/data` (así los contadores diarios y el trade abierto sobreviven a reinicios).
5. Al arrancar recibirás en Telegram "🤖 Bot OFS iniciado".

### 6) Probar sin esperar al mercado
```bash
pip install httpx
python send_example.py example_absorption.json   https://TU-APP.up.railway.app TU_SECRET
python send_example.py example_long_entry.json    https://TU-APP.up.railway.app TU_SECRET
python send_example.py example_trailing_update.json https://TU-APP.up.railway.app TU_SECRET
python send_example.py example_target_hit.json    https://TU-APP.up.railway.app TU_SECRET
```
`GET /status?secret=TU_SECRET` muestra el día, los trades abiertos y los últimos cierres.

### 7) De señal a dinero real (checklist)
- [ ] Varios días en `signals` comparando los mensajes con el gráfico.
- [ ] Varios días en `demo`: comprueba en BingX que entrada, stop y objetivo salen donde dice Telegram y que el stop se mueve en los `TRAILING`.
- [ ] `live` con riesgo mínimo (`RISK_PCT=0.1`) y un solo símbolo.
- [ ] Clave de API sin permiso de retiro.

## Escáner de todas las monedas de BingX

Con `SCAN_ENABLED=true` (por defecto) el bot analiza cada 5 minutos los **perpetuos USDT con más volumen** de BingX (`SCAN_TOP`, por defecto 40) usando datos públicos, sin API key, y aplica el mismo proceso del indicador:

1. **Entorno**: estructura de swings en 1H y 4H (velas cerradas). Equilibrio = descartada.
2. **Ubicación**: área de valor de la sesión (VAH/POC/VAL) y zona Fibonacci 0.705–0.886 fuera del valor.
3. **Confirmación**: absorción estimada con velas de 1m (delta, POC de volumen, cierre sin resultado) y primer cambio.

Qué recibes en Telegram:
- **Aviso inmediato** cuando una moneda llega a *absorción en zona* (`SCAN_ALERT_STAGE`).
- **Resumen** cada `SCAN_SUMMARY_MIN` minutos con tres grupos: absorción/primer cambio, en zona y zona lista.
- `GET /scan?secret=TU_SECRET` lanza un escaneo ahora; `GET /scan/last?secret=TU_SECRET` devuelve el último resultado en JSON.

El escáner **no opera**: avisa de setups en formación. La entrada (2º fallo) sigue viniendo del indicador de TradingView, que necesita una alerta por símbolo. Usa el escáner para saber en qué monedas poner el indicador.

Notas: respeta el límite de peticiones de BingX (~8/s); el escaneo completo tarda unos 30–60 s. Es un port en Python de la lógica del indicador, así que puede diferir en detalles (p. ej. el perfil usa las velas del día UTC). Pruébalo y compara con el gráfico antes de fiarte.

## Variables principales

Ver `.env.example`. Las más importantes: `TRADING_MODE`, `RISK_PCT`, `MAX_LEVERAGE`, `MAX_TRADES_PER_DAY`, `MAX_LOSS_STREAK`, `MIN_RR`, `MAX_SLIPPAGE_PCT`, `ALLOWED_SYMBOLS`.

## Limitaciones conocidas (léelas)

- Las señales se generan **al cierre de la vela de 5m**; el bot entra a mercado después, así que habrá deslizamiento. `MAX_SLIPPAGE_PCT` descarta entradas si el precio ya se fue.
- El resultado en R de los cierres es una **estimación** a partir del paquete (no lee el PnL realizado del exchange).
- El order flow del indicador se estima con velas de 1m, no con bid/ask real.
- La ruta de velas del escáner (`/openApi/swap/v3/quote/klines`) y el formato de los tickers también están hechos según la documentación y sin probar contra el servidor real.
- Las rutas y parámetros de BingX están implementados según su documentación pública v2, pero **no se han probado contra tu cuenta**: haz la primera prueba en `demo` y revisa los logs de Railway.
- Si Railway reinicia sin Volume, el bot pierde el estado de los trades abiertos (las órdenes de stop/objetivo siguen en BingX).
- El webhook está protegido solo por el `secret` en la URL (TradingView no permite cabeceras personalizadas). Usa uno largo y no lo compartas.

## Desarrollo

```bash
pip install -r requirements-dev.txt
pytest -q          # 23 tests: tamaño, reglas, ciclo de vida, firma BingX, webhook, escáner
uvicorn main:app --reload
```

## Archivos (todos en la raíz, sin carpetas)

```
main.py           FastAPI: /webhook /status /health
engine.py         reglas, tamaño, ejecución, gestión del stop
bingx.py          cliente BingX (firma HMAC, órdenes, cancelaciones)
tg_client.py      envío de mensajes a Telegram
messages.py       mensajes en español (4 pasos)
packet.py         lectura del JSON order-flow-strategy/v1
config.py         variables de entorno
scanner.py        escáner de todas las monedas (estructura, valor, zonas, absorción)
state.py          contadores diarios y trades abiertos (state.json)
send_example.py   envía un paquete de ejemplo a tu bot
example_*.json    paquetes de ejemplo
test_*.py         pruebas (pytest)
OFS_Indicador_ES.pine / OFS_Estrategia_Backtest_ES.pine
Dockerfile, railway.json, requirements*.txt, .env.example, .gitignore, LICENSE
```

El indicador Pine se basa en *tradingview-order-flow-strategy-indicator* de roan-maverick (MIT); la licencia y el aviso de copyright originales se mantienen en el código.
