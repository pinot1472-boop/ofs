"""Mensajes de Telegram en español (HTML), siguiendo los 4 pasos de la estrategia."""
from __future__ import annotations

from html import escape as esc
from typing import Any, Optional

from packet import Packet

STRUCT_ES = {"VALUE_UP": "Valor alcista", "VALUE_DOWN": "Valor bajista", "BALANCE": "Equilibrio"}
ZONEVOL_ES = {
    "THIN": "fino (LVN) · mejor",
    "UNTESTED": "sin testear · mejor",
    "NORMAL": "normal",
    "UNKNOWN": "n/d",
}
STATUS_ES = {
    "ACTIVE": "Activo",
    "VALUE_RECLAIMED": "Valor recuperado",
    "STOP_AT_ENTRY": "Stop en entrada",
    "NO_RECLAIM_STOP_AT_ENTRY": "Sin recuperar valor · stop en entrada",
    "TRAILING": "Trailing",
    "TARGET_HIT": "Objetivo alcanzado",
    "STOPPED": "Stop alcanzado",
    "BREAKEVEN": "Breakeven",
    "TRAIL_STOP": "Cerrado por trailing",
}
MODE_ES = {"signals": "SOLO SEÑAL", "demo": "DEMO (VST)", "live": "REAL"}


def fmt(x: Any, nd: Optional[int] = None) -> str:
    if x is None:
        return "n/d"
    try:
        v = float(x)
    except (TypeError, ValueError):
        return esc(str(x))
    if nd is None:
        nd = 2 if abs(v) >= 100 else 4
    return f"{v:,.{nd}f}"


def arrow(v: Any) -> str:
    return "▲" if v == 1 else "▼" if v == -1 else "◆"


def head(pkt: Packet, icon: str, title: str) -> str:
    return f"{icon} <b>{esc(title)}</b>\n<code>{esc(pkt.symbol_tv)}</code> · {esc(pkt.timeframe)}m · {esc(pkt.time)}"


def gamma_line(pkt: Packet) -> str:
    g = str(pkt.env("gamma_regime") or "NOT SET").upper()
    if g in ("NOT SET", "NOT_SET"):
        return "Gamma: no configurado"
    extra = []
    for k, n in (("call_wall", "call wall"), ("put_wall", "put wall"), ("gamma_flip", "flip")):
        if pkt.env(k) is not None:
            extra.append(f"{n} {fmt(pkt.env(k))}")
    es = {"NEGATIVE": "negativa (expansión)", "POSITIVE": "positiva (fallos y rango)"}.get(g, g.lower())
    return f"Gamma: {es}" + (" · " + " · ".join(extra) if extra else "")


def env_block(pkt: Packet) -> str:
    return (
        f"Estructura: <b>{STRUCT_ES.get(pkt.structure, esc(pkt.structure))}</b>"
        f" (1H {arrow(pkt.env('htf1_structure'))} · 4H {arrow(pkt.env('htf2_structure'))})\n"
        f"Ventana de trading: {'abierta' if pkt.window_open else 'cerrada'}\n"
        f"{gamma_line(pkt)}"
    )


def loc_block(pkt: Packet, side: str) -> str:
    z = pkt.zone(side)
    name = "Zona de descuento" if side == "LONG" else "Zona premium"
    lo, hi = (z.get("bottom"), z.get("top")) if side == "LONG" else (z.get("bottom"), z.get("top"))
    return (
        f"{name}: {fmt(lo)} – {fmt(hi)} · volumen {ZONEVOL_ES.get(str(z.get('zone_volume')), 'n/d')}\n"
        f"Área de valor: {fmt(pkt.loc('value_area_low'))} – {fmt(pkt.loc('value_area_high'))} · POC {fmt(pkt.loc('poc'))}"
    )


def flow_block(pkt: Packet) -> str:
    d = pkt.of("delta_pct")
    pp = pkt.of("volume_poc_position_pct")
    cp = pkt.of("close_position_pct")
    rv = pkt.of("relative_volume")
    return (
        f"Delta {fmt(d, 1)}% · POC de volumen al {fmt(pp, 0)}% de la vela · cierre al {fmt(cp, 0)}%\n"
        f"Volumen relativo {fmt(rv, 2)}x · participación {'ok' if pkt.of('participation_ok') else 'baja'}"
    )


def absorption_msg(pkt: Packet) -> str:
    sellers = bool(pkt.of("sellers_absorbed"))
    buyers = bool(pkt.of("buyers_absorbed"))
    if not (sellers or buyers):
        return ""
    who = "Vendedores absorbidos" if sellers else "Compradores absorbidos"
    side = "LONG" if sellers else "SHORT"
    z = pkt.zone(side)
    in_zone = "sí" if z.get("in_zone") else "no"
    st = pkt.of("long_state" if sellers else "short_state")
    return (
        f"{head(pkt, '🟡', '⚠ ABSORCIÓN · ' + who)}\n\n"
        f"<b>Lectura</b>\n{flow_block(pkt)}\n"
        f"En zona: {in_zone} · estado del setup: <b>{esc(str(st))}</b>\n\n"
        f"<b>Entorno</b>\n{env_block(pkt)}\n\n"
        f"ℹ️ La absorción por sí sola no es entrada. Falta primer cambio de dominio y el 2º fallo."
    )


def entry_msg(pkt: Packet, plan, mode: str, risk_info: dict, exec_note: str) -> str:
    long_ = plan.side == "LONG"
    icon = "🟢" if long_ else "🔴"
    title = f"{plan.side} · 2º FALLO"
    reclaim = pkt.trade("reclaim_level")
    trig = pkt.trade("trail_trigger")
    who = "Vendedores absorbidos" if long_ else "Compradores absorbidos"
    return (
        f"{head(pkt, icon, title)}\n"
        f"Modo: <b>{MODE_ES.get(mode, mode)}</b> · símbolo BingX: <code>{esc(plan.symbol)}</code>\n\n"
        f"<b>① Entorno</b> ✔\n{env_block(pkt)}\n\n"
        f"<b>② Ubicación</b> ✔\n{loc_block(pkt, plan.side)}\n\n"
        f"<b>③ Confirmación</b> ✔\n{who} → primer cambio → 2º fallo {'más alto' if long_ else 'más bajo'}\n{flow_block(pkt)}\n\n"
        f"<b>④ Plan</b>\n"
        f"Entrada: <b>{fmt(plan.entry)}</b>\n"
        f"Stop: <b>{fmt(plan.stop)}</b> (riesgo {fmt(plan.risk_per_unit)} por unidad)\n"
        f"Objetivo: <b>{fmt(plan.target)}</b> · {esc(plan.target_src)}\n"
        f"R:R <b>1:{plan.rr:.1f}</b>\n"
        f"Tamaño: <b>{plan.qty}</b> · riesgo <b>{fmt(plan.risk_usd, 2)} USDT</b> ({plan.risk_pct:g}% de {fmt(plan.equity, 2)})\n"
        f"Nocional {fmt(plan.notional, 2)} USDT · apalancamiento tope {plan.max_leverage:g}x"
        f"{' · <i>tamaño limitado por apalancamiento</i>' if plan.capped else ''}\n\n"
        f"<b>Gestión</b>\n"
        f"1) Volver al valor: {'sobre' if long_ else 'bajo'} {fmt(reclaim)}; si no, stop a entrada.\n"
        f"2) Objetivo final: {esc(plan.target_src)} {fmt(plan.target)}.\n"
        f"3) Trailing desde {fmt(trig)} detrás de la agresión.\n\n"
        f"<b>Reglas</b>: trade {risk_info['trades_today']}/{risk_info['max_trades']} hoy · "
        f"pérdidas seguidas {risk_info['loss_streak']}/{risk_info['max_loss_streak']}\n"
        f"⚠ <b>Invalidación</b>: cierre {'bajo' if long_ else 'sobre'} {fmt(plan.stop)}.\n"
        f"{exec_note}"
    )


def skip_msg(pkt: Packet, side: str, reasons: list[str]) -> str:
    items = "\n".join(f"• {esc(r)}" for r in reasons)
    return (
        f"{head(pkt, '⛔', 'SEÑAL DESCARTADA · ' + side)}\n\n"
        f"<b>Motivos</b>\n{items}\n\n"
        f"Entrada del indicador: {fmt(pkt.trade('entry'))} · stop {fmt(pkt.trade('stop'))} · objetivo {fmt(pkt.trade('target'))}"
    )


def update_msg(pkt: Packet, trade: dict, status: str, note: str) -> str:
    icon = {"VALUE_RECLAIMED": "✅", "STOP_AT_ENTRY": "🛡", "NO_RECLAIM_STOP_AT_ENTRY": "⚠", "TRAILING": "📈"}.get(status, "ℹ️")
    return (
        f"{head(pkt, icon, 'ACTUALIZACIÓN · ' + trade['side'] + ' · ' + STATUS_ES.get(status, status))}\n\n"
        f"Entrada {fmt(trade['entry'])} · stop <b>{fmt(pkt.trade('stop'))}</b> · objetivo {fmt(trade['target'])}\n"
        f"Precio {fmt(pkt.price('close'))}\n"
        f"{esc(note)}"
    )


def close_msg(pkt: Packet, trade: dict, status: str, result_r: float, day: dict, note: str) -> str:
    icon = "✅" if result_r > 0.05 else "❌" if result_r < -0.05 else "⚪"
    return (
        f"{head(pkt, icon, 'CIERRE · ' + trade['side'] + ' · ' + STATUS_ES.get(status, status))}\n\n"
        f"Entrada {fmt(trade['entry'])} · stop inicial {fmt(trade['stop0'])} · objetivo {fmt(trade['target'])}\n"
        f"Resultado estimado: <b>{result_r:+.2f}R</b>\n"
        f"Día: {day['day_r']:+.2f}R · trades {day['trades_today']} · pérdidas seguidas {day['loss_streak']}\n"
        f"{esc(note)}"
    )


def startup_msg(cfg) -> str:
    return (
        f"🤖 <b>Bot OFS iniciado</b>\n"
        f"Modo: <b>{MODE_ES[cfg.trading_mode]}</b>\n"
        f"Símbolos: {esc(', '.join(cfg.allowed_symbols))}\n"
        f"Riesgo {cfg.risk_pct:g}% · máx. {cfg.max_trades_per_day} trades/día · stop tras {cfg.max_loss_streak} pérdidas · R:R mín. {cfg.min_rr:g}"
    )
