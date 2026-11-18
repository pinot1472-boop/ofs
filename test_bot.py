import asyncio
import json
import os
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from config import Settings
from engine import Engine, calc_size, result_r, to_bingx_symbol
from main import create_app
from packet import PacketError, parse_packet
from state import State

EX = Path(__file__).resolve().parent


def load(name):
    return json.loads((EX / f"example_{name}.json").read_text(encoding="utf-8"))


class FakeTG:
    def __init__(self):
        self.sent = []
        self.enabled = True

    async def send(self, html):
        self.sent.append(html)
        return True

    async def aclose(self):
        pass


class FakeBX:
    def __init__(self):
        self.calls = []
        self.position_open = True
        self._n = 0

    def _id(self):
        self._n += 1
        return str(self._n)

    async def qty_rules(self, s): return 3, 0.001
    async def price_precision(self, s): return 2
    async def equity(self): return 10000.0
    async def last_price(self, s): return 62010.0
    async def set_margin_type(self, s, m): self.calls.append(("margin", m))
    async def set_leverage(self, s, l): self.calls.append(("lev", l))
    async def market_open(self, s, side, q): self.calls.append(("open", side, q)); return self._id()
    async def market_close(self, s, side, q): self.calls.append(("close", side, q)); return self._id()
    async def conditional(self, s, side, q, px, kind): self.calls.append((kind, px)); return self._id()
    async def cancel(self, s, oid): self.calls.append(("cancel", oid))
    async def positions(self, s): return [{"positionAmt": "0.05"}] if self.position_open else []
    async def aclose(self): pass


def make_cfg(mode="signals", **kw):
    env = {"WEBHOOK_SECRET": "s3cret", "TRADING_MODE": mode, "DATA_DIR": tempfile.mkdtemp(),
           "BINGX_API_KEY": "k", "BINGX_API_SECRET": "x", "ALLOWED_SYMBOLS": "BTC-USDT", "SCAN_ENABLED": "false"}
    env.update(kw)
    for k, v in env.items():
        os.environ[k] = v
    return Settings.from_env()


def make_engine(mode="signals", bx=None, **kw):
    cfg = make_cfg(mode, **kw)
    tg = FakeTG()
    return Engine(cfg, State(cfg.data_dir, cfg.tz), tg, bx), tg


def run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------- utilidades
def test_symbol_mapping():
    assert to_bingx_symbol("BINGX:BTCUSDT.P") == "BTC-USDT"
    assert to_bingx_symbol("BTCUSDT") == "BTC-USDT"
    assert to_bingx_symbol("ETH-USDT") == "ETH-USDT"


def test_sizing_rounds_down_and_caps():
    qty, risk, capped = calc_size(10000, 0.5, 62000, 61800, 3, 3, 0.001)
    assert qty == 0.25 and round(risk, 2) == 50.0 and not capped      # 50 / 200
    qty, _, capped = calc_size(10000, 0.5, 62000, 61990, 3, 3, 0.001)  # stop muy corto -> tope de apalancamiento
    assert capped and qty * 62000 <= 30000 + 62
    assert calc_size(10, 0.5, 62000, 61800, 3, 3, 0.001)[0] == 0.0     # por debajo del mínimo


def test_result_r():
    t = {"side": "LONG", "entry": 100.0, "stop": 98.0, "target": 106.0, "risk_per_unit": 2.0}
    assert result_r(t, "TARGET_HIT", None) == 3.0
    assert result_r(t, "STOPPED", None) == -1.0
    assert result_r(t, "TRAIL_STOP", 103.0) == 1.5
    s = dict(t, side="SHORT", target=94.0)
    assert result_r(s, "TARGET_HIT", None) == 3.0


def test_packet_validation():
    try:
        parse_packet({"schema": "otro"})
        assert False
    except PacketError:
        pass
    assert parse_packet(load("long_entry")).event == "LONG_ENTRY"


# -------------------------------------------------------------------- flujo
def test_signals_mode_full_lifecycle():
    eng, tg = make_engine("signals")
    r = run(eng.handle(parse_packet(load("long_entry"))))
    assert r["decision"] == "TAKE" and r["qty"] == 0.25
    assert "LONG · 2º FALLO" in tg.sent[-1] and "SOLO SEÑAL" in tg.sent[-1]
    assert eng.state.d["trades_today"] == 1

    r = run(eng.handle(parse_packet(load("trailing_update"))))
    assert r["update"] == "TRAILING" and eng.state.open_trade("BTC-USDT")["stop"] == 62150.0

    r = run(eng.handle(parse_packet(load("target_hit"))))
    assert r["closed"] == "TARGET_HIT" and r["r"] == 3.0
    assert eng.state.open_trade("BTC-USDT") is None and eng.state.d["day_r"] == 3.0


def test_duplicate_packet_ignored():
    eng, tg = make_engine("signals")
    p = parse_packet(load("long_entry"))
    run(eng.handle(p))
    assert run(eng.handle(p))["ignored"] == "duplicado"


def test_skip_reasons():
    eng, tg = make_engine("signals")
    d = load("long_entry"); d["environment"]["structure"] = "BALANCE"; d["order_flow"]["participation_ok"] = False
    r = run(eng.handle(parse_packet(d)))
    assert r["decision"] == "SKIP" and len(r["reasons"]) == 2
    assert "SEÑAL DESCARTADA" in tg.sent[-1]

    d = load("long_entry"); d["time"] = "x"; d["trade"]["target"] = 62100.0      # R:R 0.5
    r = run(eng.handle(parse_packet(d)))
    assert any("R:R" in x for x in r["reasons"])


def test_daily_limits():
    eng, tg = make_engine("signals", MAX_TRADES_PER_DAY="1")
    run(eng.handle(parse_packet(load("long_entry"))))
    run(eng.handle(parse_packet(load("target_hit"))))
    d = load("long_entry"); d["time"] = "2026-11-16T16:30:00Z"
    r = run(eng.handle(parse_packet(d)))
    assert r["decision"] == "SKIP" and any("Máximo" in x for x in r["reasons"])


def test_demo_executes_orders_and_moves_stop_safely():
    bx = FakeBX()
    eng, tg = make_engine("demo", bx=bx)
    assert run(eng.handle(parse_packet(load("long_entry"))))["decision"] == "TAKE"
    kinds = [c[0] for c in bx.calls]
    assert kinds[:5] == ["margin", "lev", "open", "STOP_MARKET", "TAKE_PROFIT_MARKET"]
    assert ("STOP_MARKET", 61800.0) in bx.calls and ("TAKE_PROFIT_MARKET", 62600.0) in bx.calls

    bx.calls.clear()
    run(eng.handle(parse_packet(load("trailing_update"))))
    # primero se crea el stop nuevo, después se cancela el viejo
    assert bx.calls[0] == ("STOP_MARKET", 62150.0) and bx.calls[1][0] == "cancel"

    bx.calls.clear()
    run(eng.handle(parse_packet(load("target_hit"))))
    assert ("close", "LONG", 0.05) in bx.calls            # la posición seguía abierta -> se cierra


def test_stop_failure_closes_position():
    class BadBX(FakeBX):
        async def conditional(self, *a, **k):
            from bingx import BingXError
            raise BingXError("boom")
    bx = BadBX()
    eng, tg = make_engine("demo", bx=bx)
    r = run(eng.handle(parse_packet(load("long_entry"))))
    assert r["decision"] == "ERROR" and any(c[0] == "close" for c in bx.calls)
    assert eng.state.open_trade("BTC-USDT") is None


def test_slippage_guard():
    class SlipBX(FakeBX):
        async def last_price(self, s): return 62500.0
    eng, tg = make_engine("demo", bx=SlipBX())
    r = run(eng.handle(parse_packet(load("long_entry"))))
    assert r["decision"] == "SKIP" and any("se alejó" in x for x in r["reasons"])


# ------------------------------------------------------------------ webhook
def test_webhook_auth_and_flow():
    eng, tg = make_engine("signals")
    with TestClient(create_app(eng)) as c:
        body = json.dumps(load("long_entry"))
        assert c.post("/webhook", content=body).status_code == 401
        assert c.post("/webhook?secret=mal", content=body).status_code == 401
        r = c.post("/webhook?secret=s3cret", content=body, headers={"Content-Type": "text/plain"})
        assert r.status_code == 200 and r.json()["event"] == "LONG_ENTRY"
        assert c.post("/webhook?secret=s3cret", content="no es json").json()["ok"] is False
        assert c.get("/status?secret=s3cret").json()["trades_today"] == 1
        assert c.get("/health").json() == {"status": "ok"}
