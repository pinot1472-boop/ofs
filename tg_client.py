"""Envío de mensajes a Telegram (HTML)."""
from __future__ import annotations

import logging
from typing import Optional

import httpx

log = logging.getLogger("telegram")


class Telegram:
    def __init__(self, token: str, chat_id: str, client: Optional[httpx.AsyncClient] = None) -> None:
        self.token = token
        self.chat_id = chat_id
        self.http = client or httpx.AsyncClient(timeout=10.0)

    @property
    def enabled(self) -> bool:
        return bool(self.token and self.chat_id)

    async def send(self, html: str) -> bool:
        if not self.enabled:
            log.info("[telegram desactivado]\n%s", html)
            return False
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        try:
            r = await self.http.post(url, json={
                "chat_id": self.chat_id,
                "text": html[:4000],
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            })
            if r.status_code != 200:
                log.error("Telegram %s: %s", r.status_code, r.text[:200])
                return False
            return True
        except httpx.HTTPError as e:
            log.error("Telegram error: %s", e)
            return False

    async def aclose(self) -> None:
        await self.http.aclose()
