# Análisis BingX – Order Flow Strategy 5m (nov 2026)

## Realidad de liquidez en BingX

BingX tiene ~180-600 pares de futuros perpetuos según la fuente.  
**Solo los 15-25 primeros tienen liquidez suficiente** para que la estimación de order flow (absorción + delta) sea fiable en 5 minutos.

### Tier S – Núcleo (máxima calidad)
| Símbolo     | Multiplier | Min RR | Comentario                          |
|-------------|------------|--------|-------------------------------------|
| BTC-USDT    | 1.00x      | 1.50   | Mejor order flow de todo BingX     |
| ETH-USDT    | 0.95x      | 1.50   | Muy limpio, ligeramente más volátil|

### Tier A – Muy recomendados
SOL, XRP, BNB, ZEC, HYPE, DOGE, NEAR, AVAX, SUI, LINK, AAVE, ADA, DOT

### Tier B – Solo con filtros duros
PEPE, ENA, TAO, UNI, TRX, LTC, BCH, ARB, OP, INJ, etc.

### Resto (~100+ monedas)
No recomendadas para 5m OFS. El order flow estimado se vuelve ruido y el slippage destruye el R:R.

## Mejoras implementadas en esta versión

1. **symbols.py** – Perfiles por símbolo (tier + risk multiplier + min RR).
2. **engine.py** – Aplica automáticamente el multiplier de riesgo y el R:R mínimo del perfil.
3. **config.py / .env.example** – Lista de símbolos recomendados (Tier S + A) por defecto.
4. Filtros más estrictos en alts de menor liquidez (vía multiplier + min RR más alto).

## Cómo usar

- Empieza **solo con BTC-USDT y ETH-USDT** en modo `demo`.
- Cuando tengas estadísticas, añade 3-5 de Tier A.
- Nunca actives 40+ símbolos a la vez en live: la calidad cae en picado.

## Nota sobre “140 monedas”

Pedir 140 monedas es contraproducente.  
La estrategia Order Flow necesita **participantes reales** que absorban.  
En monedas de bajo volumen esa condición casi nunca se cumple de forma fiable.

Esta versión prioriza **calidad sobre cantidad**.
