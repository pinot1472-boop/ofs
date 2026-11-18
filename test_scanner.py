import asyncio
import math
import time

import httpx

from bingx import BingX
from scanner import (MIN5, HOUR, Scanner, RateLimiter, absorbed, analyze, build_zones, flow_metrics,
                     format_alert, format_digest, in_zone, pivots, structure, value_profile)


def cs(closes, spread=1.0, t0=0, tf=MIN5, vol=100.0):
    return [{"t": t0 + i * tf, "o": c, "h": c + spread, "l": c - spread, "c": c, "v": vol} for i, c in enumerate(closes)]


def hl(candles):
    return [c["h"] for c in candles], [c["l"] for c in candles]


def test_structure_up_down_balance():
    up = cs([i * 0.5 + 5 * math.sin(i / 3) for i in range(120)])
    dn = cs([-i * 0.5 + 5 * math.sin(i / 3) for i in range(120)])
    flat = cs([[0, 2, 4, 2][i % 4] for i in range(120)])
    assert structure(*hl(up)) == 1
    assert structure(*hl(dn)) == -1
    assert structure(*hl(flat)) == 0


def test_value_profile_poc_inside_value():
    candles = cs([100] * 30 + [101] * 30 + [110] * 3, spread=0.5, vol=100.0)
    poc, vah, val = value_profile(candles, 0.5)
    assert val <= poc <= vah and 99 <= poc <= 102 and vah < 112


def test_flow_and_absorption():
    bar = {"t": 0, "o": 108, "h": 110, "l": 100, "c": 108, "v": 1000}
    # vendedores agresivos en el mínimo (mucho volumen bajista a ~101) y cierre lejos del mínimo
    m1 = [
        {"t": 0, "o": 105, "h": 106, "l": 100, "c": 101, "v": 600},
        {"t": 60_000, "o": 101, "h": 103, "l": 100.5, "c": 102, "v": 100},
        {"t": 120_000, "o": 102, "h": 105, "l": 101, "c": 104, "v": 100},
        {"t": 180_000, "o": 104, "h": 107, "l": 103, "c": 106, "v": 100},
        {"t": 240_000, "o": 106, "h": 110, "l": 105, "c": 108, "v": 100},
    ]
    f = flow_metrics(bar, m1)
    assert f["delta"] < -15 and f["pocpos"] < 35 and f["closepos"] == 80.0
    assert absorbed("LONG", f) and not absorbed("SHORT", f)
    assert flow_metrics(bar, []) is None


def test_zone_detection_long():
    path = list(range(100, 151, 5)) + [145, 140, 138, 140] + list(range(145, 201, 5)) + [190, 170, 150, 135, 125]
    # más barras planas al principio para que haya pivotes confirmados
    candles = cs([100] * 6 + path, spread=1.0)
    ph, pl = pivots(*hl(candles), 5)
    assert ph and pl
    z = build_zones(candles, vah=300.0, val=250.0)["long"]
    assert z and z["ready"], z
    assert abs(z["z3"] - 110.63) < 0.1 and abs(z["z1"] - 129.09) < 0.1
    assert in_zone("LONG", z, candles[-1])
    # si la zona no queda fuera del valor, no está lista
    assert not build_zones(candles, vah=300.0, val=120.0)["long"]["ready"]


def make_klines(n, tf, closes_fn, now_ms, vol=100.0):
    start = now_ms - now_ms % tf - n * tf
    return [{"t": start + i * tf, "o": closes_fn(i), "h": closes_fn(i) + 1, "l": closes_fn(i) - 1, "c": closes_fn(i), "v": vol} for i in range(n)]


def test_analyze_uptrend_returns_row_and_balance_has_stage0():
    now_ms = 1_800_000_000_000
    up = lambda i: i * 0.5 + 5 * math.sin(i / 3)
    flat = lambda i: [0, 2, 4, 2][i % 4] + 100
    k5 = make_klines(500, MIN5, lambda i: 100 + i * 0.05, now_ms)
    k1 = make_klines(70, 60_000, lambda i: 120, now_ms)
    r = analyze("AAA-USDT", k5, k1, make_klines(120, HOUR, up, now_ms), make_klines(120, 4 * HOUR, up, now_ms), now_ms)
    assert r and r.bias == 1 and r.side == "LONG" and r.stage >= 1
    r0 = analyze("BBB-USDT", k5, k1, make_klines(120, HOUR, flat, now_ms), make_klines(120, 4 * HOUR, flat, now_ms), now_ms)
    assert r0 and r0.bias == 0 and r0.stage == 0
    assert analyze("CCC-USDT", k5[:10], k1, k5, k5, now_ms) is None       # pocos datos


def test_messages_do_not_crash_and_escape():
    now_ms = 1_800_000_000_000
    up = lambda i: i * 0.5 + 5 * math.sin(i / 3)
    r = analyze("A<B>-USDT", make_klines(500, MIN5, lambda i: 100 + i * 0.05, now_ms), make_klines(70, 60_000, lambda i: 120, now_ms),
                make_klines(120, HOUR, up, now_ms), make_klines(120, 4 * HOUR, up, now_ms), now_ms)
    r.stage = 4
    r.delta, r.pocpos, r.closepos = -22.0, 12.0, 70.0
    html = format_digest([r], 1) + format_alert(r)
    assert "A&lt;B&gt;" in html and "ABSORCIÓN" in html


def test_universe_filters_and_sorts():
    def handler(req: httpx.Request) -> httpx.Response:
        if "contracts" in req.url.path:
            return httpx.Response(200, json={"code": 0, "data": [
                {"symbol": "BTC-USDT", "status": 1}, {"symbol": "ETH-USDT", "status": 1},
                {"symbol": "DEAD-USDT", "status": 0}, {"symbol": "BTC-USDC", "status": 1}, {"symbol": "TINY-USDT", "status": 1}]})
        return httpx.Response(200, json={"code": 0, "data": [
            {"symbol": "ETH-USDT", "quoteVolume": "9000000"}, {"symbol": "BTC-USDT", "quoteVolume": "50000000"},
            {"symbol": "DEAD-USDT", "quoteVolume": "99000000"}, {"symbol": "TINY-USDT", "quoteVolume": "1000"}]})

    async def go():
        bx = BingX("https://x", "", "", client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
        return await bx.usdt_universe(5_000_000, 10)

    assert asyncio.run(go()) == ["BTC-USDT", "ETH-USDT"]


def test_scanner_cycle_with_fake_exchange():
    now_ms = int(time.time() * 1000)
    up = lambda i: i * 0.5 + 5 * math.sin(i / 3)

    class FakeBX:
        async def usdt_universe(self, mv, top): return ["AAA-USDT", "BAD-USDT"]
        async def klines(self, sym, interval, limit):
            if sym == "BAD-USDT":
                raise RuntimeError("sin datos")
            tf = {"5m": MIN5, "1m": 60_000, "1h": HOUR, "4h": 4 * HOUR}[interval]
            fn = (lambda i: 100 + i * 0.05) if interval in ("5m", "1m") else up
            return make_klines(limit, tf, fn, now_ms)

    class FakeTG:
        def __init__(self): self.sent = []
        async def send(self, h): self.sent.append(h)

    class Cfg:
        scan_min_volume, scan_top, scan_alert_stage, scan_summary_min, scan_interval_min = 1, 10, 4, 60, 5

    tg = FakeTG()
    sc = Scanner(Cfg, FakeBX(), tg, limiter=RateLimiter(1000))
    asyncio.run(sc.cycle(force_summary=True))
    assert len(sc.rows) == 1 and sc.rows[0].symbol == "AAA-USDT"
    assert tg.sent and "ESCÁNER BingX" in tg.sent[-1] and "sin datos 1" in tg.sent[-1]
    assert sc.snapshot()["rows"][0]["symbol"] == "AAA-USDT"
