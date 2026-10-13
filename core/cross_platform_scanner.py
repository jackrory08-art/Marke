"""Cross-platform scan loop.

Fetches books for matched pairs, runs the edge maths and tags each result with
the pair's verification status. Only ``verified`` pairs produce *actionable*
opportunities; the rest are shown with a badge. Dismissed and rejected pairs
are not scanned.
"""

import asyncio
import logging
import time
from typing import Awaitable, Callable, Optional

from app import repo
from core.cross_platform_arb import CrossPlatformArbEngine, CrossPlatformOpportunity, MarketPair
from core.pair_store import PairStore
from polymarket_client.models import OrderBook

logger = logging.getLogger(__name__)

BookFetcher = Callable[[str], Awaitable[Optional[OrderBook]]]
_CLASS_RANK = {"verified": 0, "pending": 1, "unverified": 2}


class CrossPlatformScanner:
    def __init__(
        self,
        engine: CrossPlatformArbEngine,
        store: PairStore,
        fetchers: dict[str, BookFetcher],
        state,
        db=None,
        config=None,
        queue=None,
        emit: Optional[Callable[[str, dict], None]] = None,
        max_pairs: int = 25,
    ):
        self.engine = engine
        self.store = store
        self.fetchers = fetchers
        self.state = state
        self.db = db
        self.config = config
        self.queue = queue
        self.emit = emit or (lambda *_: None)
        self.max_pairs = max_pairs
        self.analyst = None  # set by the runner (Phase 4)
        self.current: dict[str, dict] = {}       # pair_id -> opportunity dict
        self._objects: dict[str, CrossPlatformOpportunity] = {}
        self._last_scanned: dict[str, float] = {}
        self._running = False

    @property
    def paused(self) -> bool:
        return self.config is not None and bool(getattr(self.config.mode, "paused", False))

    # ----------------------------------------------------------- selection
    def _platform_enabled(self, platform: str) -> bool:
        if platform not in self.fetchers:
            return False
        if self.config is None:
            return True
        if platform == "kalshi":
            return bool(self.config.mode.kalshi_enabled)
        if platform == "predictit":
            return bool(self.config.predictit.enabled)
        return True

    def candidates(self) -> list[MarketPair]:
        pairs = [
            p for p in self.store.all()
            if not p.dismissed and p.verification_status in _CLASS_RANK
            and all(self._platform_enabled(pl) for pl in p.platforms)
        ]
        pairs.sort(key=lambda p: (_CLASS_RANK[p.verification_status],
                                  self._last_scanned.get(p.pair_id, 0.0)))
        return pairs[: self.max_pairs]

    # ---------------------------------------------------------------- scan
    async def scan_once(self) -> list[CrossPlatformOpportunity]:
        pairs = self.candidates()
        total = len(pairs)
        self.emit("agent_state", {"state": "scanning", "detail": f"scanning {total} pairs",
                                  "progress": {"done": 0, "total": total}})
        found: list[CrossPlatformOpportunity] = []
        results = await asyncio.gather(*(self._scan_pair(p) for p in pairs))
        for opp in results:
            if opp is not None:
                found.append(opp)
        self._publish()
        self.state.cross_platform["last_scan"] = {
            "pairs": total, "opportunities": len(found), "at": time.time()}
        if self.queue is None or self.queue.pending_count() == 0:
            actionable = [o for o in found if o.actionable]
            if actionable:
                self.emit("agent_state", {
                    "state": "found", "detail": f"{len(actionable)} actionable",
                    "progress": {"done": total, "total": total}})
            else:
                self.emit("agent_state", {"state": "idle", "detail": f"scanned {total} pairs",
                                          "progress": {"done": total, "total": total}})
        return found

    async def _scan_pair(self, pair: MarketPair) -> Optional[CrossPlatformOpportunity]:
        self._last_scanned[pair.pair_id] = time.monotonic()
        try:
            book_a, book_b = await asyncio.gather(
                self.fetchers[pair.platform_a](pair.market_a_id),
                self.fetchers[pair.platform_b](pair.market_b_id))
        except Exception as e:
            logger.debug("Book fetch failed for %s: %s", pair.pair_id, e)
            return None
        if book_a is None or book_b is None:
            self._drop(pair.pair_id)
            pair.live_edge = False
            return None

        opp = self.engine.check_pair(pair, book_a, book_b)
        pair.live_edge = opp is not None
        if opp is None:
            self._drop(pair.pair_id)
            return None

        previous = self.current.get(pair.pair_id)
        self._objects[pair.pair_id] = opp
        data = opp.to_dict()
        if previous and previous.get("id") == data["id"]:
            # Keep analysis the analyst attached to this same opportunity
            data["analysis"] = previous.get("analysis")
            data["quality_score"] = previous.get("quality_score")
        self.current[pair.pair_id] = data

        is_new = previous is None or previous.get("id") != data["id"] \
            or previous.get("actionable") != data["actionable"]
        if is_new:
            self.emit("opportunity", data)
        if pair.verification_status == "pending" and self.queue is not None:
            self.queue.enqueue(pair.pair_id)
        await self._record_history(opp)
        if self.analyst is not None and opp.actionable:
            asyncio.create_task(self._analyse(opp))
        return opp

    async def _analyse(self, opp: CrossPlatformOpportunity) -> None:
        try:
            await self.analyst.analyse_and_attach(opp, self)
        except Exception:
            logger.exception("Analyst failed for %s", opp.opportunity_key)

    def _drop(self, pair_id: str) -> None:
        self.current.pop(pair_id, None)
        self._objects.pop(pair_id, None)

    def _publish(self) -> None:
        opps = sorted(self.current.values(), key=lambda o: o["net_edge"], reverse=True)
        self.state.cross_platform["cross_opportunities"] = opps[:100]

    async def _record_history(self, opp: CrossPlatformOpportunity) -> None:
        if self.db is None:
            return

        def write():
            with self.db.session() as s:
                repo.upsert_history(
                    s, opp.opportunity_key, kind="cross_platform", pair_key=opp.pair_id,
                    platforms="|".join(opp.market_pair.platforms),
                    market_a_id=opp.market_pair.market_a_id,
                    market_b_id=opp.market_pair.market_b_id,
                    net_edge=opp.net_edge, gross_edge=opp.gross_edge, fees=opp.fees,
                    depth=opp.depth, verification_status=opp.verification_status,
                    actionable=opp.actionable)
        try:
            await asyncio.to_thread(write)
        except Exception:
            logger.exception("Failed to record opportunity history")

    # ------------------------------------------------------------- hooks
    async def on_pair_verified(self, pair: MarketPair) -> None:
        """Called by the queue after a verdict: refresh the opportunity's gate fields."""
        opp = self._objects.get(pair.pair_id)
        data = self.current.get(pair.pair_id)
        if opp is None or data is None:
            return
        opp.verification_status = pair.verification_status
        opp.actionable = pair.verification_status == "verified" and not pair.dismissed
        data["verification_status"] = opp.verification_status
        data["actionable"] = opp.actionable
        data["verdict"] = pair.verification or None
        self._publish()
        self.emit("opportunity", data)
        if self.analyst is not None and opp.actionable:
            asyncio.create_task(self._analyse(opp))

    def on_pair_dismissed(self, pair_id: str) -> None:
        self._drop(pair_id)
        self._publish()

    def attach_analysis(self, opp: CrossPlatformOpportunity, analysis: dict) -> None:
        data = self.current.get(opp.pair_id)
        if data is None or data.get("id") != opp.opportunity_key:
            return
        data["analysis"] = analysis
        data["quality_score"] = analysis.get("quality_score")
        self._publish()

    # ---------------------------------------------------------------- loop
    async def run(self, interval: float = 10.0) -> None:
        self._running = True
        while self._running:
            try:
                if self.store.all() and not self.paused:
                    await self.scan_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Cross-platform scan failed")
            await asyncio.sleep(interval)

    def stop(self) -> None:
        self._running = False
