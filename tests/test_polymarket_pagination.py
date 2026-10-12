import json

import httpx
import pytest

from polymarket_client.api import PolymarketClient


def market(i: int) -> dict:
    return {"id": str(i), "conditionId": f"0x{i}", "question": f"Market {i}?",
            "clobTokenIds": json.dumps([f"yes{i}", f"no{i}"]), "active": True}


def make_client(pages):
    """Client whose Gamma API returns ``pages`` in order; an Exception item is raised."""
    client = PolymarketClient(rest_url="http://x", ws_url="ws://x", gamma_url="http://g", dry_run=True)
    calls = []

    async def fake_request(method, path, params=None, **kw):
        calls.append(params["offset"])
        item = pages[len(calls) - 1]
        if isinstance(item, Exception):
            raise item
        return item
    client._request = fake_request
    client._calls = calls
    return client


def http_error(code: int) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "http://g/markets")
    return httpx.HTTPStatusError(f"HTTP {code}", request=request,
                                 response=httpx.Response(code, request=request))


async def test_pagination_limit_422_keeps_markets_already_loaded(monkeypatch):
    async def no_sleep(_):
        pass
    monkeypatch.setattr("polymarket_client.api.asyncio.sleep", no_sleep)
    full = [market(i) for i in range(100)]
    client = make_client([full, full, http_error(422)])
    markets = await client.list_markets({"active": True})
    assert len(markets) == 200 and client._calls == [0, 100, 200]


async def test_first_page_failure_is_still_an_error():
    client = make_client([http_error(422)])
    with pytest.raises(httpx.HTTPStatusError):
        await client.list_markets({"active": True})


async def test_server_errors_mid_pagination_are_not_swallowed(monkeypatch):
    async def no_sleep(_):
        pass
    monkeypatch.setattr("polymarket_client.api.asyncio.sleep", no_sleep)
    client = make_client([[market(i) for i in range(100)], http_error(500)])
    with pytest.raises(httpx.HTTPStatusError):
        await client.list_markets({"active": True})
