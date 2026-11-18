"""Perfiles de símbolos BingX para OFS 5m.

Tier S  = máxima liquidez y order flow limpio (BTC, ETH)
Tier A  = muy buena liquidez, volatilidad útil
Tier B  = aceptable con filtros más estrictos
Tier C  = solo señales / evitar en live

Los multipliers reducen el riesgo en monedas menos líquidas.
"""
from __future__ import annotations

from typing import Dict, Tuple

# (tier, risk_multiplier, min_rel_vol, min_rr, note)
SYMBOL_PROFILES: Dict[str, Tuple[str, float, float, float, str]] = {
    # ── Tier S ──────────────────────────────────────────────────────────────
    "BTC-USDT":   ("S", 1.00, 1.20, 1.50, "Núcleo. Mejor order flow de todo BingX"),
    "ETH-USDT":   ("S", 0.95, 1.25, 1.50, "Núcleo. Muy limpio, ligeramente más volátil"),

    # ── Tier A ──────────────────────────────────────────────────────────────
    "SOL-USDT":   ("A", 0.80, 1.50, 1.60, "Alta liquidez + buena volatilidad 5m"),
    "XRP-USDT":   ("A", 0.75, 1.50, 1.60, "Liquidez sólida, patrones de absorción claros"),
    "BNB-USDT":   ("A", 0.75, 1.50, 1.60, "Buen book, menos ruido que la mayoría de alts"),
    "ZEC-USDT":   ("A", 0.70, 1.60, 1.70, "Volumen sorprendente, usar con cuidado"),
    "HYPE-USDT":  ("A", 0.70, 1.60, 1.70, "Alta volatilidad, buena para R:R altos"),
    "DOGE-USDT":  ("A", 0.65, 1.60, 1.70, "Liquidez decente, spreads aceptables"),
    "NEAR-USDT":  ("A", 0.65, 1.60, 1.70, "Buen movimiento intradía"),
    "AVAX-USDT":  ("A", 0.65, 1.60, 1.70, "Volatilidad útil"),
    "SUI-USDT":   ("A", 0.60, 1.70, 1.80, "Liquidez media-alta"),
    "LINK-USDT":  ("A", 0.60, 1.70, 1.80, "Clásico, book estable"),
    "AAVE-USDT":  ("A", 0.60, 1.70, 1.80, "Buenas absorciones en zonas clave"),
    "ADA-USDT":   ("A", 0.55, 1.70, 1.80, "Liquidez aceptable"),
    "DOT-USDT":   ("A", 0.55, 1.70, 1.80, "Movimientos claros"),

    # ── Tier B ──────────────────────────────────────────────────────────────
    "PEPE-USDT":  ("B", 0.45, 2.00, 2.00, "Meme – solo con volumen extremo"),
    "ENA-USDT":   ("B", 0.45, 2.00, 2.00, "Volatilidad alta, spreads variables"),
    "TAO-USDT":   ("B", 0.45, 2.00, 2.00, "Movimientos grandes, menos liquidez"),
    "UNI-USDT":   ("B", 0.50, 1.80, 1.90, "DeFi clásico"),
    "TRX-USDT":   ("B", 0.50, 1.80, 1.90, "Volumen estable pero bajo"),
    "LTC-USDT":   ("B", 0.50, 1.80, 1.90, "Clásico, spreads aceptables"),
    "BCH-USDT":   ("B", 0.45, 1.90, 2.00, "Menor liquidez relativa"),
    "ATOM-USDT":  ("B", 0.45, 1.90, 2.00, "Movimientos decentes"),
    "FIL-USDT":   ("B", 0.40, 2.00, 2.00, "Spreads más amplios"),
    "APT-USDT":   ("B", 0.45, 1.90, 2.00, "Volatilidad útil"),
    "ARB-USDT":   ("B", 0.45, 1.90, 2.00, "L2 – volumen medio"),
    "OP-USDT":    ("B", 0.45, 1.90, 2.00, "L2 – volumen medio"),
    "INJ-USDT":   ("B", 0.40, 2.00, 2.00, "Alta volatilidad"),
    "SEI-USDT":   ("B", 0.40, 2.00, 2.00, "Movimientos rápidos"),
    "TIA-USDT":   ("B", 0.40, 2.00, 2.00, "Volatilidad alta"),
    "WIF-USDT":   ("B", 0.35, 2.20, 2.20, "Meme – muy selectivo"),
    "BONK-USDT":  ("B", 0.35, 2.20, 2.20, "Meme – muy selectivo"),
    "ORDI-USDT":  ("B", 0.40, 2.00, 2.00, "Inscriptions – selectivo"),
    "SATS-USDT":  ("B", 0.35, 2.20, 2.20, "Muy especulativo"),
    "1000PEPE-USDT": ("B", 0.35, 2.20, 2.20, "Meme – solo volumen extremo"),
}

# Lista recomendada para ALLOWED_SYMBOLS (solo S + A por defecto)
RECOMMENDED_ALLOWED = [
    "BTC-USDT", "ETH-USDT",
    "SOL-USDT", "XRP-USDT", "BNB-USDT", "ZEC-USDT", "HYPE-USDT",
    "DOGE-USDT", "NEAR-USDT", "AVAX-USDT", "SUI-USDT", "LINK-USDT",
    "AAVE-USDT", "ADA-USDT", "DOT-USDT",
]

def get_profile(symbol: str) -> Tuple[str, float, float, float, str]:
    """Devuelve (tier, risk_mult, min_rel_vol, min_rr, note). Default = Tier C restrictivo."""
    return SYMBOL_PROFILES.get(symbol.upper(), ("C", 0.30, 2.50, 2.50, "No perfilado – muy restrictivo"))


def risk_multiplier(symbol: str) -> float:
    return get_profile(symbol)[1]


def min_rr_for(symbol: str, default: float = 1.5) -> float:
    return max(default, get_profile(symbol)[3])
