"""Motor: convierte paquetes del indicador en decisiones, órdenes en BingX y mensajes de Telegram."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Optional

from bingx import BingX, BingXError, floor_to
from config import Settings
from messages import (absorption_msg, close_msg, entry_msg, skip_msg, update_msg)
from packet import Packet
from state import State
from tg_client import Telegram

log = logging.getLogger("engine")

CLOSING = ("TARGET_HIT", "STOPPED", "BREAKEVEN", "TRAIL_STOP")
STOP_MOVES = ("STOP_AT_ENTRY", "NO_RECLAIM_STOP_AT_ENTRY", "TRAILING")


def to_bingx_symbol(tv_symbol: str) -> str:
    """BINGX:BTCUSDT.P -> BTC-USDT"""
    s = tv_symbol.split(":")[-1].upper().replace(".P", "").replace("PERP", "")
    if "-" in s:
        return s
    for quote in ("USDT", "USDC", "USD"):
        if s.endswith(quote) and len(s) > len(quote):
            return f"{s[:-len(quote)]}-{quote}"
    return s


@dataclass
class Plan:
    side: str
    symbol: str
    entry: float
    stop: float
    target: float
    target_src: str
    rr: float
    qty: float
    risk_usd: float
    risk_pct: float
    risk_per_unit: float
    notional: float
    equity: float
    max_leverage: float
    capped: bool


def calc_size(equity: float, risk_pct: float, entry: float, stop: float, max_leverage: float,
              qty_precision: int, min_qty: float) -> tuple[float, float, bool]:
    """Tamaño = (equity × riesgo%) / |entrada − stop|, limitado por apalancamiento y redondeado hacia abajo."""
    dist = abs(entry - stop)
    if dist <= 0 or entry <= 0:
        return 0.0, 0.0, False
    qty = equity * risk_pct / 100.0 / dist
    cap = equity * max_leverage / entry
    capped = qty > cap
    qty = floor_to(min(qty, cap), qty_precision)
    if qty < min_qty:
        return 0.0, 0.0, capped
    return qty, qty * dist, capped


def result_r(trade: dict, status: str, final_stop: Optional[float]) -> float:
    risk = trade["risk_per_unit"]
    d = 1 if trade["side"] == "LONG" else -1
    if risk <= 0:
        return 0.0
    if status == "TARGET_HIT":
        return d * (trade["target"] - trade["entry"]) / risk
    if status == "STOPPED":
        return -1.0
    if status == "BREAKEVEN":
        return 0.0
    if status == "TRAIL_STOP":
        stop = final_stop if final_stop is not None else trade["stop"]
        return d * (stop - trade["entry"]) / risk
    return 0.0


class Engine:
    def __init__(self, cfg: Settings, state: State, tg: Telegram, bx: Optional[BingX]) -> None:
        self.cfg = cfg
        self.state = state
        self.tg = tg
        self.bx = bx
        self.lock = asyncio.Lock()

    # ------------------------------------------------------------------ entrada
    async def handle(self, pkt: Packet) -> dict:
        async with self.lock:
            self.state.roll_day()
            key = f"{pkt.symbol_tv}|{pkt.timeframe}|{pkt.time}|{pkt.event}|{pkt.trade_status}"
            if self.state.seen(key):
                return {"ok": True, "ignored": "duplicado"}
            ev = pkt.event
            if ev in ("LONG_ENTRY", "SHORT_ENTRY"):
                return await self._entry(pkt, "LONG" if ev == "LONG_ENTRY" else "SHORT")
            if ev == "TRADE_UPDATE":
                return await self._update(pkt)
            if ev == "ABSORPTION":
                if self.cfg.notify_absorption:
                    msg = absorption_msg(pkt)
                    if msg:
                        await self.tg.send(msg)
                return {"ok": True, "event": ev}
            return {"ok": True, "ignored": ev}

    # ------------------------------------------------------------------- reglas
    def _reasons(self, pkt: Packet, side: str, symbol: str) -> list[str]:
        r: list[str] = []
        cfg, st = self.cfg, self.state.d
        if symbol not in cfg.allowed_symbols:
            r.append(f"{symbol} no está en ALLOWED_SYMBOLS")
        want = "VALUE_UP" if side == "LONG" else "VALUE_DOWN"
        if pkt.structure != want:
            r.append(f"Estructura {pkt.structure or 'n/d'}: un {side} exige {want}")
        if not pkt.window_open:
            r.append("Ventana de trading cerrada")
        if not pkt.of("participation_ok"):
            r.append("Participación baja")
        if self.state.open_trade(symbol):
            r.append("Ya hay un trade abierto en este símbolo")
        if st["trades_today"] >= cfg.max_trades_per_day:
            r.append(f"Máximo de {cfg.max_trades_per_day} trades por día alcanzado")
        if st["loss_streak"] >= cfg.max_loss_streak:
            r.append(f"{st['loss_streak']} pérdidas seguidas: parado por hoy")
        entry, stop, target = pkt.trade("entry"), pkt.trade("stop"), pkt.trade("target")
        if None in (entry, stop, target):
            r.append("El paquete no trae entrada, stop u objetivo")
        else:
            risk = (entry - stop) if side == "LONG" else (stop - entry)
            reward = (target - entry) if side == "LONG" else (entry - target)
            if risk <= 0:
                r.append("Stop en el lado equivocado de la entrada")
            elif reward / risk < cfg.min_rr:
                r.append(f"R:R 1:{reward / risk:.2f} < mínimo 1:{cfg.min_rr:g}")
        return r

    # ------------------------------------------------------------------ entradas
    async def _entry(self, pkt: Packet, side: str) -> dict:
        cfg = self.cfg
        symbol = to_bingx_symbol(pkt.symbol_tv)
        reasons = self._reasons(pkt, side, symbol)
        entry, stop, target = pkt.trade("entry"), pkt.trade("stop"), pkt.trade("target")

        qty_prec, min_qty, equity = 3, 0.0, cfg.account_size
        if not reasons and cfg.executes_orders and self.bx:
            try:
                qty_prec, min_qty = await self.bx.qty_rules(symbol)
                equity = await self.bx.equity()
                last = await self.bx.last_price(symbol)
                if abs(last - entry) / entry * 100 > cfg.max_slippage_pct:
                    reasons.append(f"Precio actual {last:,.2f} se alejó {abs(last - entry) / entry * 100:.2f}% de la entrada (máx. {cfg.max_slippage_pct}%)")
                if (side == "LONG" and last <= stop) or (side == "SHORT" and last >= stop):
                    reasons.append("El precio ya rompió el stop")
            except BingXError as e:
                reasons.append(f"Error consultando BingX: {e}")

        plan: Optional[Plan] = None
        if not reasons:
            qty, risk_usd, capped = calc_size(equity, cfg.risk_pct, entry, stop, cfg.max_leverage, qty_prec, min_qty)
            if qty <= 0:
                reasons.append("Tamaño calculado por debajo del mínimo del contrato")
            else:
                dist = abs(entry - stop)
                plan = Plan(side=side, symbol=symbol, entry=entry, stop=stop, target=target,
                            target_src=str(pkt.trade("target_source") or "R"),
                            rr=abs(target - entry) / dist, qty=qty, risk_usd=risk_usd,
                            risk_pct=cfg.risk_pct, risk_per_unit=dist, notional=qty * entry,
                            equity=equity, max_leverage=cfg.max_leverage, capped=capped)

        if plan is None:
            if cfg.notify_skips:
                await self.tg.send(skip_msg(pkt, side, reasons))
            return {"ok": True, "decision": "SKIP", "reasons": reasons}

        trade = {
            "symbol": symbol, "side": side, "entry": plan.entry, "stop": plan.stop, "stop0": plan.stop,
            "target": plan.target, "qty": plan.qty, "risk_per_unit": plan.risk_per_unit,
            "opened": pkt.time, "sl_id": None, "tp_id": None, "mode": cfg.trading_mode,
        }
        note = "📨 Solo señal: no se envió ninguna orden."
        if cfg.executes_orders and self.bx:
            try:
                note = await self._open_position(trade)
            except BingXError as e:
                await self.tg.send(skip_msg(pkt, side, [f"Fallo al ejecutar en BingX: {e}"]))
                return {"ok": False, "decision": "ERROR", "error": str(e)}

        self.state.d["trades_today"] += 1
        self.state.set_open(symbol, trade)
        info = {"trades_today": self.state.d["trades_today"], "max_trades": cfg.max_trades_per_day,
                "loss_streak": self.state.d["loss_streak"], "max_loss_streak": cfg.max_loss_streak}
        await self.tg.send(entry_msg(pkt, plan, cfg.trading_mode, info, note))
        return {"ok": True, "decision": "TAKE", "side": side, "qty": plan.qty}

    async def _open_position(self, trade: dict) -> str:
        bx, cfg = self.bx, self.cfg
        sym, side, qty = trade["symbol"], trade["side"], trade["qty"]
        await bx.set_margin_type(sym, cfg.margin_type)
        await bx.set_leverage(sym, cfg.leverage)
        await bx.market_open(sym, side, qty)
        pp = await bx.price_precision(sym)
        try:
            trade["sl_id"] = await bx.conditional(sym, side, qty, round(trade["stop"], pp), "STOP_MARKET")
            trade["tp_id"] = await bx.conditional(sym, side, qty, round(trade["target"], pp), "TAKE_PROFIT_MARKET")
        except BingXError:
            # Nunca dejar una posición sin stop: cerrar de inmediato.
            await bx.market_close(sym, side, qty)
            raise BingXError("No se pudo colocar el stop/objetivo; la posición se cerró a mercado")
        return f"✅ Orden enviada a BingX ({cfg.trading_mode}): mercado + stop + objetivo."

    # -------------------------------------------------------------- actualizaciones
    async def _update(self, pkt: Packet) -> dict:
        symbol = to_bingx_symbol(pkt.symbol_tv)
        trade = self.state.open_trade(symbol)
        if not trade:
            return {"ok": True, "ignored": "sin trade abierto"}
        if pkt.trade_side != trade["side"]:
            return {"ok": True, "ignored": "lado distinto"}
        status = pkt.trade_status
        new_stop = pkt.trade("stop")

        if status in CLOSING:
            r = result_r(trade, status, new_stop)
            note = await self._reconcile_close(trade)
            closed = self.state.close_trade(symbol, r, status)
            await self.tg.send(close_msg(pkt, closed, status, r, self.state.d, note))
            return {"ok": True, "closed": status, "r": round(r, 2)}

        note = {
            "VALUE_RECLAIMED": "Primer checkpoint superado: el precio volvió al valor.",
            "STOP_AT_ENTRY": "Riesgo off: stop movido a la entrada.",
            "NO_RECLAIM_STOP_AT_ENTRY": "No recuperó el valor a tiempo: stop movido a la entrada.",
            "TRAILING": "El stop sigue ahora cada vela con agresión a favor.",
        }.get(status, "")
        if status in STOP_MOVES and new_stop is not None:
            improved = new_stop > trade["stop"] if trade["side"] == "LONG" else new_stop < trade["stop"]
            if improved:
                if self.cfg.executes_orders and self.bx:
                    try:
                        await self._move_stop(trade, new_stop)
                        note += f" Stop en BingX actualizado a {new_stop:,.2f}."
                    except BingXError as e:
                        note += f" ⚠ No se pudo mover el stop en BingX: {e}"
                trade["stop"] = new_stop
                self.state.set_open(symbol, trade)
        await self.tg.send(update_msg(pkt, trade, status, note))
        return {"ok": True, "update": status}

    async def _move_stop(self, trade: dict, new_stop: float) -> None:
        """Coloca el stop nuevo ANTES de cancelar el viejo (nunca hay un hueco sin protección)."""
        bx = self.bx
        pp = await bx.price_precision(trade["symbol"])
        new_id = await bx.conditional(trade["symbol"], trade["side"], trade["qty"], round(new_stop, pp), "STOP_MARKET")
        old = trade.get("sl_id")
        trade["sl_id"] = new_id
        if old:
            await bx.cancel(trade["symbol"], old)

    async def _reconcile_close(self, trade: dict) -> str:
        if not (self.cfg.executes_orders and self.bx):
            return "Modo solo señal: cierre virtual."
        bx, sym = self.bx, trade["symbol"]
        try:
            for oid in (trade.get("sl_id"), trade.get("tp_id")):
                if oid:
                    await bx.cancel(sym, oid)
            left = [p for p in await bx.positions(sym)]
            if left:
                for p in left:
                    await bx.market_close(sym, trade["side"], abs(float(p["positionAmt"])))
                return "La posición seguía abierta en BingX: cerrada a mercado."
            return "Posición ya cerrada en BingX; órdenes pendientes canceladas."
        except BingXError as e:
            return f"⚠ Revisa BingX manualmente: {e}"
