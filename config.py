"""Configuración del bot (todo por variables de entorno)."""
from __future__ import annotations

import os
from dataclasses import dataclass


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _f(name: str, default: float) -> float:
    v = _env(name)
    return float(v) if v else default


def _i(name: str, default: int) -> int:
    v = _env(name)
    return int(v) if v else default


def _b(name: str, default: bool) -> bool:
    v = _env(name).lower()
    if not v:
        return default
    return v in ("1", "true", "yes", "on", "si", "sí")


MODES = ("signals", "demo", "live")


@dataclass(frozen=True)
class Settings:
    webhook_secret: str
    trading_mode: str          # signals = solo Telegram | demo = BingX VST | live = dinero real
    bingx_api_key: str
    bingx_api_secret: str
    bingx_base_url: str
    position_mode: str         # hedge | oneway
    telegram_token: str
    telegram_chat_id: str
    account_size: float        # usado solo en modo signals
    risk_pct: float
    leverage: int
    max_leverage: float        # tope nocional / equity
    margin_type: str           # ISOLATED | CROSSED
    max_trades_per_day: int
    max_loss_streak: int
    min_rr: float
    max_slippage_pct: float
    allowed_symbols: tuple
    notify_absorption: bool
    notify_skips: bool
    data_dir: str
    tz: str
    scan_enabled: bool
    scan_interval_min: int
    scan_top: int
    scan_min_volume: float
    scan_alert_stage: int
    scan_summary_min: int
    scan_base_url: str

    @property
    def executes_orders(self) -> bool:
        return self.trading_mode in ("demo", "live")

    @classmethod
    def from_env(cls) -> "Settings":
        mode = _env("TRADING_MODE", "signals").lower()
        if mode not in MODES:
            raise ValueError(f"TRADING_MODE debe ser uno de {MODES}, no '{mode}'")
        secret = _env("WEBHOOK_SECRET")
        if not secret:
            raise ValueError("Falta WEBHOOK_SECRET")
        default_base = "https://open-api-vst.bingx.com" if mode == "demo" else "https://open-api.bingx.com"
        s = cls(
            webhook_secret=secret,
            trading_mode=mode,
            bingx_api_key=_env("BINGX_API_KEY"),
            bingx_api_secret=_env("BINGX_API_SECRET"),
            bingx_base_url=_env("BINGX_BASE_URL") or default_base,
            position_mode=_env("POSITION_MODE", "hedge").lower(),
            telegram_token=_env("TELEGRAM_BOT_TOKEN"),
            telegram_chat_id=_env("TELEGRAM_CHAT_ID"),
            account_size=_f("ACCOUNT_SIZE", 10000.0),
            risk_pct=_f("RISK_PCT", 0.5),
            leverage=_i("LEVERAGE", 3),
            max_leverage=_f("MAX_LEVERAGE", 3.0),
            margin_type=_env("MARGIN_TYPE", "ISOLATED").upper(),
            max_trades_per_day=_i("MAX_TRADES_PER_DAY", 2),
            max_loss_streak=_i("MAX_LOSS_STREAK", 2),
            min_rr=_f("MIN_RR", 1.5),
            max_slippage_pct=_f("MAX_SLIPPAGE_PCT", 0.15),
            allowed_symbols=tuple(x.strip().upper() for x in _env("ALLOWED_SYMBOLS", "BTC-USDT").split(",") if x.strip()),
            notify_absorption=_b("NOTIFY_ABSORPTION", True),
            notify_skips=_b("NOTIFY_SKIPS", True),
            data_dir=_env("DATA_DIR", "."),
            tz=_env("DAILY_RESET_TZ", "UTC"),
            scan_enabled=_b("SCAN_ENABLED", True),
            scan_interval_min=_i("SCAN_INTERVAL_MIN", 5),
            scan_top=_i("SCAN_TOP", 40),
            scan_min_volume=_f("SCAN_MIN_VOLUME", 5_000_000.0),
            scan_alert_stage=_i("SCAN_ALERT_STAGE", 4),
            scan_summary_min=_i("SCAN_SUMMARY_MIN", 60),
            scan_base_url=_env("SCAN_BASE_URL", "https://open-api.bingx.com"),
        )
        if s.position_mode not in ("hedge", "oneway"):
            raise ValueError("POSITION_MODE debe ser hedge u oneway")
        if s.executes_orders and not (s.bingx_api_key and s.bingx_api_secret):
            raise ValueError("Modo demo/live requiere BINGX_API_KEY y BINGX_API_SECRET")
        return s
