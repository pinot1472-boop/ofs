"""Servidor FastAPI: recibe los webhooks de TradingView."""
from __future__ import annotations

import hmac
import json
import logging
import asyncio
from contextlib import asynccontextmanager

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request

from bingx import BingX
from config import Settings
from engine import Engine
from messages import startup_msg
from packet import PacketError, parse_packet
from scanner import Scanner
from state import State
from tg_client import Telegram

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("main")


def build_engine(cfg: Settings) -> Engine:
    bx = BingX(cfg.bingx_base_url, cfg.bingx_api_key, cfg.bingx_api_secret, cfg.position_mode) if cfg.executes_orders else None
    return Engine(cfg, State(cfg.data_dir, cfg.tz), Telegram(cfg.telegram_token, cfg.telegram_chat_id), bx)


def build_scanner(engine: Engine) -> Scanner:
    # Datos de mercado públicos: siempre contra el host real, sin claves.
    public = BingX(engine.cfg.scan_base_url, "", "", engine.cfg.position_mode)
    return Scanner(engine.cfg, public, engine.tg)


def create_app(engine: Engine | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.engine = engine or build_engine(Settings.from_env())
        cfg = app.state.engine.cfg
        app.state.scanner = build_scanner(app.state.engine) if cfg.scan_enabled else None
        await app.state.engine.tg.send(startup_msg(cfg) + (
            f"\nEscáner: top {cfg.scan_top} por volumen cada {cfg.scan_interval_min} min" if cfg.scan_enabled else ""))
        task = asyncio.create_task(app.state.scanner.loop()) if app.state.scanner else None
        yield
        if task:
            task.cancel()
        if app.state.scanner:
            await app.state.scanner.bx.aclose()
        await app.state.engine.tg.aclose()
        if app.state.engine.bx:
            await app.state.engine.bx.aclose()

    app = FastAPI(title="OFS → BingX + Telegram", lifespan=lifespan)

    def _auth(request: Request, secret: str | None) -> None:
        expected = request.app.state.engine.cfg.webhook_secret
        if not secret or not hmac.compare_digest(secret, expected):
            raise HTTPException(status_code=401, detail="secret inválido")

    @app.get("/")
    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.get("/status")
    async def status(request: Request, secret: str | None = None):
        _auth(request, secret)
        e = request.app.state.engine
        d = e.state.d
        return {"mode": e.cfg.trading_mode, "day": d["day"], "trades_today": d["trades_today"],
                "loss_streak": d["loss_streak"], "day_r": d["day_r"], "open": d["open"],
                "last_closed": d["history"][-5:]}

    @app.get("/scan")
    async def scan(request: Request, background: BackgroundTasks, secret: str | None = None):
        """Lanza un escaneo ahora y manda el resumen a Telegram."""
        _auth(request, secret)
        sc = request.app.state.scanner
        if not sc:
            raise HTTPException(status_code=404, detail="SCAN_ENABLED=false")
        background.add_task(_scan_now, sc)
        return {"ok": True, "msg": "Escaneo iniciado; el resumen llegará a Telegram"}

    @app.get("/scan/last")
    async def scan_last(request: Request, secret: str | None = None):
        _auth(request, secret)
        sc = request.app.state.scanner
        if not sc:
            raise HTTPException(status_code=404, detail="SCAN_ENABLED=false")
        return sc.snapshot()

    @app.post("/webhook")
    async def webhook(request: Request, background: BackgroundTasks, secret: str | None = None):
        _auth(request, secret)
        raw = (await request.body()).decode("utf-8", errors="replace").strip()
        try:
            pkt = parse_packet(json.loads(raw))
        except (ValueError, PacketError) as e:      # JSON inválido o schema distinto
            log.warning("Paquete ignorado: %s", e)
            return {"ok": False, "error": str(e)}
        # TradingView espera respuesta rápida: procesamos en segundo plano.
        background.add_task(_process, request.app.state.engine, pkt)
        return {"ok": True, "event": pkt.event}

    return app


async def _process(engine: Engine, pkt) -> None:
    try:
        res = await engine.handle(pkt)
        log.info("%s -> %s", pkt.event, res)
    except Exception:  # noqa: BLE001
        log.exception("Error procesando %s", pkt.event)
        await engine.tg.send(f"🚨 <b>Error del bot</b> procesando {pkt.event}. Revisa los logs de Railway.")


async def _scan_now(scanner: Scanner) -> None:
    try:
        await scanner.cycle(force_summary=True)
    except Exception:  # noqa: BLE001
        log.exception("Fallo en /scan")


app = create_app()
