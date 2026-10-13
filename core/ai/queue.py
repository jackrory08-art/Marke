"""Background queue that verifies pairs, edge-first then most-similar-first."""

import asyncio
import itertools
import logging
from typing import Callable, Optional

from core.pair_store import PairStore

logger = logging.getLogger(__name__)

Emit = Callable[[str, dict], None]


class VerificationQueue:
    """Pulls pairs, verifies them, updates the store and emits dashboard events."""

    # Reasons for "unverified" worth retrying later (not a deliberate kill switch)
    RETRYABLE = {"backoff", "provider_error", "rate_limited", "bad_output",
                 "budget_exhausted", "provider_unavailable", "unexpected_error"}

    def __init__(
        self, verifier, store: PairStore, emit: Optional[Emit] = None, workers: int = 2,
        on_verified: Optional[Callable] = None, retry_interval_s: float = 900.0,
    ):
        self.verifier = verifier
        self.store = store
        self.emit = emit or (lambda *_: None)
        self.on_verified = on_verified  # async callable(pair) after a verdict is stored
        self._workers = max(1, workers)
        self._queue: asyncio.PriorityQueue = asyncio.PriorityQueue()
        self._queued: set[str] = set()
        self._counter = itertools.count()
        self._tasks: list[asyncio.Task] = []
        self._batch_total = 0
        self._batch_done = 0
        self._force: set[str] = set()
        self._retry_interval_s = retry_interval_s
        self.pause_check: Optional[Callable[[], bool]] = None  # True while processing is paused

    # ------------------------------------------------------------- control
    def start(self) -> None:
        if self._tasks:
            return
        self._tasks = [asyncio.create_task(self._worker()) for _ in range(self._workers)]
        self._tasks.append(asyncio.create_task(self._retry_loop()))

    async def _retry_loop(self) -> None:
        """Periodically retry pairs that failed for a transient reason."""
        while True:
            await asyncio.sleep(self._retry_interval_s)
            self.retry_unverified()

    def retry_unverified(self) -> int:
        n = 0
        for pair in self.store.all():
            reason = (pair.verification or {}).get("reason")
            if pair.verification_status == "unverified" and reason in self.RETRYABLE:
                n += bool(self.enqueue(pair.pair_id))
        return n

    async def stop(self) -> None:
        for t in self._tasks:
            t.cancel()
        for t in self._tasks:
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass
        self._tasks = []

    # ------------------------------------------------------------ enqueueing
    def enqueue(self, pair_id: str, force: bool = False) -> bool:
        pair = self.store.get(pair_id)
        if pair is None or pair_id in self._queued:
            return False
        priority = 0 if pair.live_edge else 1
        if force:
            self._force.add(pair_id)
            priority = -1
        self._queued.add(pair_id)
        self._batch_total += 1
        self._queue.put_nowait((priority, -pair.similarity_score, next(self._counter), pair_id))
        self._emit_state("verifying", f"{self._batch_done}/{self._batch_total} queued")
        return True

    def enqueue_pending(self) -> int:
        return sum(1 for p in self.store.all()
                   if p.verification_status == "pending" and self.enqueue(p.pair_id))

    def pending_count(self) -> int:
        return len(self._queued)

    # --------------------------------------------------------------- worker
    async def _worker(self) -> None:
        while True:
            _prio, _sim, _n, pair_id = await self._queue.get()
            while self.pause_check is not None and self.pause_check():
                await asyncio.sleep(1.0)
            try:
                await self._process(pair_id)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Verification worker error for %s", pair_id)
            finally:
                self._queued.discard(pair_id)
                self._force.discard(pair_id)
                self._batch_done += 1
                if self._queue.empty() and not self._queued:
                    total = self._batch_total
                    self._batch_total = self._batch_done = 0
                    self._emit_state("idle", f"verified {total} pairs", done=total, total=total)
                else:
                    self._emit_state("verifying", f"checking pair {self._batch_done + 1}/{self._batch_total}")

    async def _process(self, pair_id: str) -> None:
        pair = self.store.get(pair_id)
        if pair is None:
            return
        self.emit("verification_started", {
            "pair_id": pair_id, "platforms": list(pair.platforms),
            "titles": [pair.title_a, pair.title_b],
            "position": self._batch_done + 1, "total": self._batch_total,
        })
        result = await self.verifier.verify(pair, force=pair_id in self._force)
        details = result.to_dict()
        self.store.set_verification(pair_id, result.status, details)
        self.emit("verification_finished", {
            "pair_id": pair_id, "status": result.status, "verdict": result.verdict,
            "confidence": result.confidence, "differences": result.differences,
            "short_reason": result.short_reason, "reason": result.reason,
            "cached": result.cached,
        })
        if self.on_verified is not None:
            try:
                await self.on_verified(pair)
            except Exception:
                logger.exception("on_verified hook failed")

    def _emit_state(self, state: str, detail: str, done: Optional[int] = None,
                    total: Optional[int] = None) -> None:
        self.emit("agent_state", {
            "state": state, "detail": detail,
            "progress": {"done": self._batch_done if done is None else done,
                         "total": self._batch_total if total is None else total},
        })
