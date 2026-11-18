import asyncio
import hashlib
import hmac
from urllib.parse import parse_qsl, urlsplit

import httpx

from bingx import BingX, floor_to


def test_floor_to():
    assert floor_to(0.2579, 3) == 0.257
    assert floor_to(1.0, 0) == 1.0


def test_signed_request_and_order_parsing():
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["req"] = req
        return httpx.Response(200, json={"code": 0, "msg": "", "data": {"order": {"orderId": 123456}}})

    async def go():
        bx = BingX("https://open-api.bingx.com", "KEY", "SECRET", "hedge",
                   client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
        return await bx.conditional("BTC-USDT", "LONG", 0.25, 61800.0, "STOP_MARKET")

    assert asyncio.run(go()) == "123456"
    req = seen["req"]
    assert req.method == "POST" and req.headers["X-BX-APIKEY"] == "KEY"
    parts = urlsplit(str(req.url))
    qs = dict(parse_qsl(parts.query))
    sig = qs.pop("signature")
    unsigned = "&".join(f"{k}={qs[k]}" for k in sorted(qs))
    assert sig == hmac.new(b"SECRET", unsigned.encode(), hashlib.sha256).hexdigest()
    assert qs["side"] == "SELL" and qs["positionSide"] == "LONG" and qs["type"] == "STOP_MARKET"
    assert qs["stopPrice"] == "61800.0" and qs["quantity"] == "0.25"


def test_api_error_raises():
    import pytest
    from bingx import BingXError

    def handler(req):
        return httpx.Response(200, json={"code": 100400, "msg": "bad"})

    async def go():
        bx = BingX("https://x", "k", "s", client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
        await bx.equity()

    with pytest.raises(BingXError):
        asyncio.run(go())
