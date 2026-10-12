"""Read-only PredictIt client.

PredictIt data is licensed for non-commercial use only. The source refreshes
about once a minute, so this client never polls faster than that and keeps the
last response in memory between polls.
"""

import asyncio
import logging
import time
from typing import Callable, Optional

import httpx

from core.market_ref import ComparableMarket
from polymarket_client.models import OrderBook
from predictit_client.models import (
    PredictItMarket, contract_to_orderbook, parse_all,
)

logger = logging.getLogger(__name__)

MIN_POLL_INTERVAL_S = 60.0
USER_AGENT = "Marke/2.0 (non-commercial prediction-market monitor)"


class PredictItClient:
    def __init__(
        self, config, *, transport: Optional[httpx.AsyncBaseTransport] = None,
        sleep=asyncio.sleep, monotonic: Callable[[], float] = time.monotonic,
    ):
        self.config = config
        self._http = httpx.AsyncClient(
            timeout=config.timeout_s, transport=transport,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
        self._sleep = sleep
        self._mono = monotonic
        self._markets: list[PredictItMarket] = []
        self._books: dict[str, OrderBook] = {}
        self._fetched_at: Optional[float] = None
        self._lock = asyncio.Lock()
        self.request_count = 0

    @property
    def poll_interval_s(self) -> float:
        return max(MIN_POLL_INTERVAL_S, float(self.config.poll_interval_s))

    async def aclose(self) -> None:
        await self._http.aclose()

    # ----------------------------------------------------------------- fetch
    async def get_markets(self, force: bool = False) -> list[PredictItMarket]:
        """Markets from memory, refreshed at most once per poll interval."""
        async with self._lock:
            fresh = self._fetched_at is not None and \
                self._mono() - self._fetched_at < self.poll_interval_s
            if fresh and not force:
                return self._markets
            try:
                payload = await self._request()
            except Exception as e:
                logger.warning("PredictIt fetch failed: %s", e)
                self._fetched_at = self._mono()      # back off for a full interval
                return self._markets                  # serve the last good data
            self._markets = parse_all(payload)
            self._books = {}
            for m in self._markets:
                if not m.is_open:
                    continue
                for c in m.contracts:
                    if c.is_open:
                        book = contract_to_orderbook(m.contract_key(m.id, c.id), c)
                        if book is not None:
                            self._books[m.contract_key(m.id, c.id)] = book
            self._fetched_at = self._mono()
            logger.info("PredictIt: %d markets, %d priced contracts",
                        len(self._markets), len(self._books))
            return self._markets

    async def _request(self):
        last: Optional[Exception] = None
        for attempt in range(self.config.max_retries):
            self.request_count += 1
            try:
                res = await self._http.get(self.config.api_url)
                if res.status_code >= 500 or res.status_code == 429:
                    raise httpx.HTTPStatusError(
                        f"HTTP {res.status_code}", request=res.request, response=res)
                res.raise_for_status()
                return res.json()
            except (httpx.TransportError, httpx.HTTPStatusError, ValueError) as e:
                last = e
                if isinstance(e, httpx.HTTPStatusError) and e.response.status_code < 500 \
                        and e.response.status_code != 429:
                    break                              # a 4xx will not get better
                if attempt + 1 < self.config.max_retries:
                    await self._sleep(min(30.0, 2.0 ** attempt))
        raise last or RuntimeError("PredictIt request failed")

    # ------------------------------------------------------------ cached views
    def comparable_markets(self) -> list[ComparableMarket]:
        refs: list[ComparableMarket] = []
        for m in self._markets:
            if m.is_open:
                refs.extend(m.to_comparable())
        return refs

    def get_orderbook(self, contract_key: str) -> Optional[OrderBook]:
        return self._books.get(contract_key)

    async def fetch_orderbook(self, contract_key: str) -> Optional[OrderBook]:
        """Scanner-facing: serve from the polled data (no extra HTTP call)."""
        return self._books.get(contract_key)


def build_predictit_client(config) -> Optional[PredictItClient]:
    """None unless ``predictit.enabled`` is set (it is off by default)."""
    pi = config.predictit
    return PredictItClient(pi) if pi.enabled else None
