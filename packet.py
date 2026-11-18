"""Lectura del paquete JSON del indicador (schema order-flow-strategy/v1)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

SCHEMA = "order-flow-strategy/v1"


class PacketError(ValueError):
    pass


def _g(d: Any, *path: str) -> Any:
    for p in path:
        if not isinstance(d, dict):
            return None
        d = d.get(p)
    return d


@dataclass
class Packet:
    raw: dict

    @property
    def event(self) -> str:
        return str(self.raw.get("event", ""))

    @property
    def symbol_tv(self) -> str:
        return str(self.raw.get("symbol", ""))

    @property
    def timeframe(self) -> str:
        return str(self.raw.get("timeframe", ""))

    @property
    def time(self) -> str:
        return str(self.raw.get("time", ""))

    def price(self, k: str) -> Optional[float]:
        return _g(self.raw, "price", k)

    @property
    def structure(self) -> str:
        return str(_g(self.raw, "environment", "structure") or "")

    @property
    def window_open(self) -> bool:
        return bool(_g(self.raw, "environment", "window_open"))

    def env(self, k: str) -> Any:
        return _g(self.raw, "environment", k)

    def loc(self, k: str) -> Any:
        return _g(self.raw, "location", k)

    def zone(self, side: str) -> dict:
        return _g(self.raw, "location", "long_zone" if side == "LONG" else "short_zone") or {}

    def of(self, k: str) -> Any:
        return _g(self.raw, "order_flow", k)

    def risk(self, k: str) -> Any:
        return _g(self.raw, "risk", k)

    def trade(self, k: str) -> Any:
        return _g(self.raw, "trade", k)

    @property
    def trade_side(self) -> str:
        return str(self.trade("side") or "NONE")

    @property
    def trade_status(self) -> str:
        return str(self.trade("status") or "NONE")


def parse_packet(data: Any) -> Packet:
    if not isinstance(data, dict):
        raise PacketError("El cuerpo no es un objeto JSON")
    if data.get("schema") != SCHEMA:
        raise PacketError(f"schema desconocido: {data.get('schema')!r}")
    if not data.get("event") or not data.get("symbol"):
        raise PacketError("Falta event o symbol")
    return Packet(raw=data)
