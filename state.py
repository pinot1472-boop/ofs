"""Estado persistente (JSON). En Railway monta un Volume en DATA_DIR para sobrevivir a reinicios."""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo


class State:
    def __init__(self, data_dir: str, tz: str = "UTC") -> None:
        self.path = os.path.join(data_dir, "state.json")
        self.tz = ZoneInfo(tz)
        self._lock = threading.Lock()
        os.makedirs(data_dir, exist_ok=True)
        self.d: dict = {
            "day": "",
            "trades_today": 0,
            "loss_streak": 0,
            "day_r": 0.0,
            "seen": [],
            "open": {},       # symbol -> trade dict
            "history": [],    # últimos trades cerrados
        }
        self._load()
        self.roll_day()

    def _load(self) -> None:
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                self.d.update(json.load(f))
        except (FileNotFoundError, json.JSONDecodeError):
            pass

    def save(self) -> None:
        with self._lock:
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.d, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)

    def today(self) -> str:
        return datetime.now(self.tz).strftime("%Y-%m-%d")

    def roll_day(self) -> None:
        t = self.today()
        if self.d.get("day") != t:
            self.d["day"] = t
            self.d["trades_today"] = 0
            self.d["loss_streak"] = 0
            self.d["day_r"] = 0.0
            self.save()

    def seen(self, key: str) -> bool:
        """True si ya se procesó (TradingView puede reintentar el webhook)."""
        if key in self.d["seen"]:
            return True
        self.d["seen"].append(key)
        self.d["seen"] = self.d["seen"][-300:]
        self.save()
        return False

    def open_trade(self, symbol: str) -> Optional[dict]:
        return self.d["open"].get(symbol)

    def set_open(self, symbol: str, trade: dict) -> None:
        self.d["open"][symbol] = trade
        self.save()

    def close_trade(self, symbol: str, result_r: float, status: str) -> Optional[dict]:
        trade = self.d["open"].pop(symbol, None)
        if trade is None:
            return None
        trade["closed_status"] = status
        trade["result_r"] = round(result_r, 2)
        self.d["history"].append(trade)
        self.d["history"] = self.d["history"][-100:]
        self.d["day_r"] = round(self.d["day_r"] + result_r, 2)
        if status == "STOPPED":
            self.d["loss_streak"] += 1
        elif status in ("TARGET_HIT", "TRAIL_STOP"):
            self.d["loss_streak"] = 0
        self.save()
        return trade
