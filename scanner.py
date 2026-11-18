"""Escáner de todas las monedas de BingX con el proceso de la estrategia (entorno → ubicación → confirmación).

Port en Python de la lógica del indicador OFS usando datos públicos de BingX (sin API key):
  ① Entorno      estructura de swings en 1H y 4H (velas cerradas)
  ② Ubicación    área de valor de la sesión (VAH/POC/VAL) + zona Fibonacci 0.705–0.886 fuera del valor
  ③ Confirmación absorción estimada con velas de 1m (delta, POC de volumen, cierre sin resultado) y primer cambio

El escáner NO opera: avisa de setups en formación. La entrada (2º fallo) la sigue dando el indicador en TradingView.
"""
from __future__ import annotations

import asyncio
import logging
import math
import time
from dataclasses import asdict, dataclass
from html import escape as esc
from typing import Optional

log = logging.getLogger("scanner")

MIN5 = 300_000
HOUR = 3_600_000
DAY = 86_400_000

STAGE_ES = {
    0: "Equilibrio · sin trade",
    1: "Valor alineado · sin zona válida",
    2: "Zona lista · esperando al precio",
    3: "En zona · vigilar absorción",
    4: "ABSORCIÓN en zona",
    5: "PRIMER CAMBIO · armado (falta 2º fallo)",
}


# ------------------------------------------------------------------ funciones puras
def pivots(h: list[float], l: list[float], n: int) -> tuple[list[tuple[int, float]], list[tuple[int, float]]]:
    ph, pl = [], []
    for i in range(n, len(h) - n):
        if h[i] == max(h[i - n:i + n + 1]) and h[i] > max(h[i - n:i]):
            ph.append((i, h[i]))
        if l[i] == min(l[i - n:i + n + 1]) and l[i] < min(l[i - n:i]):
            pl.append((i, l[i]))
    return ph, pl


def structure(h: list[float], l: list[float], n: int = 3) -> int:
    """1 = valor alcista (HH+HL), -1 = valor bajista (LH+LL), 0 = equilibrio."""
    ph, pl = pivots(h, l, n)
    if len(ph) < 2 or len(pl) < 2:
        return 0
    h1, h2, l1, l2 = ph[-1][1], ph[-2][1], pl[-1][1], pl[-2][1]
    return 1 if h1 > h2 and l1 > l2 else -1 if h1 < h2 and l1 < l2 else 0


def atr(cs: list[dict], n: int = 14) -> float:
    if len(cs) < 2:
        return 0.0
    trs = [max(cs[i]["h"] - cs[i]["l"], abs(cs[i]["h"] - cs[i - 1]["c"]), abs(cs[i]["l"] - cs[i - 1]["c"])) for i in range(1, len(cs))]
    a = sum(trs[:n]) / min(n, len(trs))
    for t in trs[n:]:
        a = (a * (n - 1) + t) / n
    return a


def value_profile(cs: list[dict], step: float, pct: float = 0.70) -> Optional[tuple[float, float, float]]:
    """(POC, VAH, VAL) de un perfil de volumen repartido por filas de precio."""
    if not cs or step <= 0:
        return None
    vols: dict[int, float] = {}
    for c in cs:
        lo = math.floor(c["l"] / step)
        hi = max(lo, min(lo + 300, math.floor(c["h"] / step)))
        share = c["v"] / (hi - lo + 1)
        for k in range(lo, hi + 1):
            vols[k] = vols.get(k, 0.0) + share
    k0, k1 = min(vols), max(vols)
    total = sum(vols.values())
    if total <= 0:
        return None
    poc_k = max(range(k0, k1 + 1), key=lambda k: (vols.get(k, 0.0), -k))
    up = dn = poc_k
    acc = vols.get(poc_k, 0.0)
    while acc < total * pct and (up < k1 or dn > k0):
        v_up = vols.get(up + 1, 0.0) if up < k1 else -1.0
        v_dn = vols.get(dn - 1, 0.0) if dn > k0 else -1.0
        if v_up >= v_dn:
            up += 1
            acc += v_up
        else:
            dn -= 1
            acc += v_dn
    return (poc_k + 0.5) * step, (up + 1) * step, dn * step


def build_zones(cs: list[dict], vah: Optional[float], val: Optional[float], swing: int = 5, look: int = 60,
                fa: float = 0.705, fc: float = 0.886) -> dict:
    """Zonas de descuento (long) y premium (short) sobre la última pierna impulsiva."""
    h, l = [c["h"] for c in cs], [c["l"] for c in cs]
    ph, pl = pivots(h, l, swing)
    out: dict = {"long": None, "short": None}

    if ph:
        ih, hp = ph[-1]
        start = max(0, ih - look + 1)
        low_w = l[start:ih + 1]
        lL = min(low_w)
        iL = start + low_w.index(lL)
        lH = max(max(h[ih:]), hp)
        if lH > lL:
            z1, z3 = lH - fa * (lH - lL), lH - fc * (lH - lL)
            valid = all(c["c"] >= z3 for c in cs[ih + 1:])
            internal = any(iL < i < ih and p > lL for i, p in pl)
            ready = valid and internal and val is not None and z1 <= val
            out["long"] = {"z1": z1, "z3": z3, "ready": ready, "origin": lL, "leg_high": lH}

    if pl:
        il, lp = pl[-1]
        start = max(0, il - look + 1)
        high_w = h[start:il + 1]
        sH = max(high_w)
        iH = start + high_w.index(sH)
        sL = min(min(l[il:]), lp)
        if sH > sL:
            z1, z3 = sL + fa * (sH - sL), sL + fc * (sH - sL)
            valid = all(c["c"] <= z3 for c in cs[il + 1:])
            internal = any(iH < i < il and p < sH for i, p in ph)
            ready = valid and internal and vah is not None and z1 >= vah
            out["short"] = {"z1": z1, "z3": z3, "ready": ready, "origin": sH, "leg_low": sL}
    return out


def in_zone(side: str, z: Optional[dict], c: dict) -> bool:
    if not z or not z["ready"]:
        return False
    if side == "LONG":
        return c["l"] <= z["z1"] and c["c"] >= z["z3"]
    return c["h"] >= z["z1"] and c["c"] <= z["z3"]


def flow_metrics(bar: dict, m1: list[dict]) -> Optional[dict]:
    """Delta %, posición del POC de volumen y del cierre dentro de la vela 5m, estimados con velas de 1m."""
    if not m1:
        return None
    vol = sum(x["v"] for x in m1)
    if vol <= 0:
        return None
    signed = sum(x["v"] if x["c"] > x["o"] else -x["v"] if x["c"] < x["o"] else 0.0 for x in m1)
    top = max(m1, key=lambda x: x["v"])
    rng = bar["h"] - bar["l"]
    poc_mid = (top["h"] + top["l"]) / 2
    return {
        "delta": signed / vol * 100,
        "pocpos": (poc_mid - bar["l"]) / rng * 100 if rng > 0 else 50.0,
        "closepos": (bar["c"] - bar["l"]) / rng * 100 if rng > 0 else 50.0,
    }


def absorbed(side: str, f: dict, min_delta: float = 15, poc_zone: float = 35, no_result: float = 30) -> bool:
    if side == "LONG":      # vendedores absorbidos
        return f["delta"] <= -min_delta and f["pocpos"] <= poc_zone and f["closepos"] >= no_result
    return f["delta"] >= min_delta and f["pocpos"] >= 100 - poc_zone and f["closepos"] <= 100 - no_result


# ------------------------------------------------------------------------ análisis
@dataclass
class Row:
    symbol: str
    price: float
    bias: int
    s1: int
    s4: int
    stage: int
    side: str = ""
    z_lo: Optional[float] = None
    z_hi: Optional[float] = None
    vah: Optional[float] = None
    poc: Optional[float] = None
    val: Optional[float] = None
    delta: Optional[float] = None
    pocpos: Optional[float] = None
    closepos: Optional[float] = None
    relvol: Optional[float] = None
    dist_atr: Optional[float] = None
    abs_time: int = 0
    vol24h: float = 0.0


def closed(cs: list[dict], tf_ms: int, now_ms: int) -> list[dict]:
    return [c for c in cs if c["t"] + tf_ms <= now_ms]


def analyze(symbol: str, k5: list[dict], k1: list[dict], k1h: list[dict], k4h: list[dict], now_ms: int,
            vol24h: float = 0.0) -> Optional[Row]:
    c5, c1 = closed(k5, MIN5, now_ms), closed(k1, 60_000, now_ms)
    ch1, ch4 = closed(k1h, HOUR, now_ms), closed(k4h, 4 * HOUR, now_ms)
    if len(c5) < 60 or len(ch1) < 20 or len(ch4) < 20:
        return None
    s1 = structure([c["h"] for c in ch1], [c["l"] for c in ch1])
    s4 = structure([c["h"] for c in ch4], [c["l"] for c in ch4])
    bias = 1 if s1 == 1 and s4 >= 0 else -1 if s1 == -1 and s4 <= 0 else 0
    last = c5[-1]
    row = Row(symbol=symbol, price=last["c"], bias=bias, s1=s1, s4=s4, stage=0, vol24h=vol24h)
    if bias == 0:
        return row

    a5 = atr(c5)
    day0 = now_ms - now_ms % DAY
    session = [c for c in c5 if c["t"] >= day0]
    prof = value_profile(session, max(a5 * 0.5, 1e-12)) if len(session) >= 12 else None
    row.side = "LONG" if bias == 1 else "SHORT"
    row.stage = 1
    if not prof:
        return row
    row.poc, row.vah, row.val = prof

    z = build_zones(c5, row.vah, row.val)[("long" if bias == 1 else "short")]
    if not z or not z["ready"]:
        return row
    row.stage = 2
    row.z_lo, row.z_hi = min(z["z1"], z["z3"]), max(z["z1"], z["z3"])
    p = last["c"]
    gap = (p - z["z1"]) if bias == 1 else (z["z1"] - p)
    row.dist_atr = max(0.0, gap / a5) if a5 > 0 else None
    avg_v = sum(c["v"] for c in c5[-50:]) / min(50, len(c5))
    row.relvol = last["v"] / avg_v if avg_v > 0 else None

    if in_zone(row.side, z, last):
        row.stage = 3

    # absorción en las últimas 8 velas (con la zona tocada) y primer cambio posterior
    abs_i = None
    for i in range(len(c5) - 8, len(c5)):
        bar = c5[i]
        m1 = [x for x in c1 if bar["t"] <= x["t"] < bar["t"] + MIN5]
        f = flow_metrics(bar, m1)
        if f and in_zone(row.side, z, bar) and absorbed(row.side, f):
            abs_i = i
            row.delta, row.pocpos, row.closepos, row.abs_time = f["delta"], f["pocpos"], f["closepos"], bar["t"]
    if abs_i is not None:
        row.stage = 4
        later = c5[abs_i + 1:]
        if any((x["c"] > x["o"]) if row.side == "LONG" else (x["c"] < x["o"]) for x in later):
            row.stage = 5
    return row


# ------------------------------------------------------------------------ mensajes
def _fmt(x: Optional[float]) -> str:
    if x is None:
        return "n/d"
    return f"{x:,.2f}" if abs(x) >= 100 else f"{x:,.4f}" if abs(x) >= 1 else f"{x:,.6f}"


def _arrow(v: int) -> str:
    return "▲" if v == 1 else "▼" if v == -1 else "◆"


def row_detail(r: Row) -> str:
    icon = "🟢" if r.side == "LONG" else "🔴"
    zone_name = "descuento" if r.side == "LONG" else "premium"
    lines = [
        f"{icon} <b>{esc(r.symbol)}</b> · {r.side} · {STAGE_ES[r.stage]}",
        f"Precio {_fmt(r.price)} · 1H {_arrow(r.s1)} 4H {_arrow(r.s4)} · zona de {zone_name} {_fmt(r.z_lo)} – {_fmt(r.z_hi)}",
        f"Valor {_fmt(r.val)} – {_fmt(r.vah)} · POC {_fmt(r.poc)}",
    ]
    if r.delta is not None:
        lines.append(f"Delta {r.delta:+.0f}% · POC de volumen al {r.pocpos:.0f}% de la vela · cierre al {r.closepos:.0f}%")
    if r.dist_atr is not None and r.stage == 2:
        lines.append(f"A {r.dist_atr:.1f} ATR de la zona")
    return "\n".join(lines)


def format_alert(r: Row) -> str:
    return (
        f"🔎 <b>ESCÁNER · SETUP EN FORMACIÓN</b>\n\n{row_detail(r)}\n\n"
        f"ℹ️ Aún no es entrada: falta el 2º fallo que confirma el indicador de TradingView. "
        f"Si ya tienes alerta en este símbolo, espera su paquete."
    )


def format_digest(rows: list[Row], total: int, errors: int = 0) -> str:
    longs = sum(1 for r in rows if r.bias == 1)
    shorts = sum(1 for r in rows if r.bias == -1)
    flat = sum(1 for r in rows if r.bias == 0)
    out = [
        f"🔎 <b>ESCÁNER BingX</b> · {total} monedas analizadas",
        f"Valor alcista {longs} · bajista {shorts} · equilibrio {flat}" + (f" · sin datos {errors}" if errors else ""),
    ]
    groups = [
        ("🎯 Absorción / primer cambio en zona", [r for r in rows if r.stage >= 4]),
        ("📍 En zona (vigilar absorción)", [r for r in rows if r.stage == 3]),
        ("👀 Zona lista, esperando precio", [r for r in rows if r.stage == 2][:6]),
    ]
    any_ = False
    for title, rs in groups:
        if rs:
            any_ = True
            out.append(f"\n<b>{title}</b>")
            out.extend(row_detail(r) + "\n" for r in rs)
    if not any_:
        out.append("\nNingún setup en formación ahora mismo. Sin ventaja clara: no hace falta hacer nada.")
    return "\n".join(out)


# --------------------------------------------------------------------------- escáner
class RateLimiter:
    def __init__(self, per_sec: float) -> None:
        self.gap = 1.0 / per_sec
        self._next = 0.0
        self._lock = asyncio.Lock()

    async def wait(self) -> None:
        async with self._lock:
            now = time.monotonic()
            if now < self._next:
                await asyncio.sleep(self._next - now)
            self._next = max(time.monotonic(), self._next) + self.gap


class Scanner:
    def __init__(self, cfg, bx, tg, limiter: Optional[RateLimiter] = None) -> None:
        self.cfg, self.bx, self.tg = cfg, bx, tg
        self.limiter = limiter or RateLimiter(8.0)          # BingX permite ~10 peticiones/s en datos de mercado
        self.rows: list[Row] = []
        self.last_run = 0.0
        self._sent: set[str] = set()
        self._last_summary = 0.0
        self._universe: list[tuple[str, float]] = []
        self._universe_at = 0.0
        self._htf: dict[str, tuple[float, list, list]] = {}

    async def _get(self, coro_fn, *a):
        await self.limiter.wait()
        return await coro_fn(*a)

    async def _symbols(self) -> list[str]:
        if time.time() - self._universe_at > 1800 or not self._universe:
            syms = await self.bx.usdt_universe(self.cfg.scan_min_volume, self.cfg.scan_top)
            self._universe, self._universe_at = [(s, 0.0) for s in syms], time.time()
        return [s for s, _ in self._universe]

    async def _scan_symbol(self, sym: str, now_ms: int) -> Optional[Row]:
        k5 = await self._get(self.bx.klines, sym, "5m", 500)
        k1 = await self._get(self.bx.klines, sym, "1m", 70)
        cached = self._htf.get(sym)
        if not cached or time.time() - cached[0] > 600:
            k1h = await self._get(self.bx.klines, sym, "1h", 120)
            k4h = await self._get(self.bx.klines, sym, "4h", 120)
            self._htf[sym] = (time.time(), k1h, k4h)
        _, k1h, k4h = self._htf[sym]
        return analyze(sym, k5, k1, k1h, k4h, now_ms)

    async def run_once(self) -> tuple[list[Row], int, int]:
        now_ms = int(time.time() * 1000)
        syms = await self._symbols()
        sem = asyncio.Semaphore(4)
        errors = 0

        async def one(s: str):
            nonlocal errors
            async with sem:
                try:
                    return await self._scan_symbol(s, now_ms)
                except Exception as e:  # noqa: BLE001
                    errors += 1
                    log.warning("scan %s: %s", s, e)
                    return None

        res = await asyncio.gather(*(one(s) for s in syms))
        rows = [r for r in res if r]
        rows.sort(key=lambda r: (-r.stage, r.dist_atr if r.dist_atr is not None else 99.0))
        self.rows, self.last_run = rows, time.time()
        return rows, len(syms), errors

    async def cycle(self, force_summary: bool = False) -> None:
        rows, total, errors = await self.run_once()
        for r in rows:
            if r.stage >= self.cfg.scan_alert_stage:
                key = f"{r.symbol}|{r.side}|{r.abs_time}|{r.stage}"
                if key not in self._sent:
                    self._sent.add(key)
                    await self.tg.send(format_alert(r))
        self._sent = set(list(self._sent)[-500:])
        due = time.time() - self._last_summary >= self.cfg.scan_summary_min * 60
        if force_summary or (due and self.cfg.scan_summary_min > 0):
            self._last_summary = time.time()
            await self.tg.send(format_digest(rows, total, errors))

    async def loop(self) -> None:
        while True:
            try:
                await self.cycle()
            except Exception:  # noqa: BLE001
                log.exception("Fallo en el escáner")
            # espera hasta el siguiente cierre de vela de 5m + 15 s
            period = max(1, self.cfg.scan_interval_min) * 60
            await asyncio.sleep(period - (time.time() % period) + 15)

    def snapshot(self) -> dict:
        return {"last_run": int(self.last_run), "rows": [asdict(r) for r in self.rows[:50]]}
