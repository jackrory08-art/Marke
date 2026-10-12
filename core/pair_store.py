"""In-memory registry of matched pairs and their verification state.

The matcher runs in a worker thread, the verification queue and scanner run on
the event loop and the dashboard reads from request threads, so all access
goes through one lock.
"""

import threading
from typing import Iterable, Optional

from core.cross_platform_arb import MarketPair

STATUSES = ("pending", "verified", "rejected", "unverified", "dismissed")


class PairStore:
    def __init__(self):
        self._pairs: dict[str, MarketPair] = {}
        self._dismissed: set[str] = set()
        self._lock = threading.RLock()

    # ------------------------------------------------------------- mutation
    def set_dismissed_keys(self, keys: Iterable[str]) -> None:
        with self._lock:
            self._dismissed = set(keys)
            for pid, pair in self._pairs.items():
                pair.dismissed = pid in self._dismissed

    def add_many(self, pairs: Iterable[MarketPair]) -> list[MarketPair]:
        """Add pairs; known ids keep their existing verification state.

        Returns the pairs that were new.
        """
        new = []
        with self._lock:
            for pair in pairs:
                if pair.pair_id in self._pairs:
                    continue
                pair.dismissed = pair.pair_id in self._dismissed
                self._pairs[pair.pair_id] = pair
                new.append(pair)
        return new

    def set_verification(self, pair_id: str, status: str, details: dict) -> Optional[MarketPair]:
        with self._lock:
            pair = self._pairs.get(pair_id)
            if pair is None:
                return None
            pair.verification_status = status
            pair.verification = details
            return pair

    def set_dismissed(self, pair_id: str, dismissed: bool) -> Optional[MarketPair]:
        with self._lock:
            pair = self._pairs.get(pair_id)
            if dismissed:
                self._dismissed.add(pair_id)
            else:
                self._dismissed.discard(pair_id)
            if pair is not None:
                pair.dismissed = dismissed
            return pair

    # ---------------------------------------------------------------- reads
    def get(self, pair_id: str) -> Optional[MarketPair]:
        with self._lock:
            return self._pairs.get(pair_id)

    def all(self) -> list[MarketPair]:
        with self._lock:
            return list(self._pairs.values())

    def list(self, status: Optional[str] = None, platform: Optional[str] = None) -> list[MarketPair]:
        with self._lock:
            pairs = list(self._pairs.values())
        if status:
            pairs = [p for p in pairs if p.status == status]
        if platform:
            pairs = [p for p in pairs if platform in p.platforms]
        return pairs

    def counts(self) -> dict[str, int]:
        counts = {s: 0 for s in STATUSES}
        for p in self.all():
            counts[p.status] = counts.get(p.status, 0) + 1
        counts["total"] = sum(counts[s] for s in STATUSES)
        return counts

    def clear(self) -> None:
        with self._lock:
            self._pairs.clear()


def pair_to_public(pair: MarketPair) -> dict:
    return {
        "pair_id": pair.pair_id,
        "platforms": list(pair.platforms),
        "market_a_id": pair.market_a_id,
        "market_b_id": pair.market_b_id,
        "title_a": pair.title_a,
        "title_b": pair.title_b,
        "similarity": round(pair.similarity_score, 4),
        "category": pair.category,
        "status": pair.status,
        "verification_status": pair.verification_status,
        "dismissed": pair.dismissed,
        "live_edge": pair.live_edge,
        "verdict": pair.verification or None,
        "refs": [r.to_public() for r in (pair.ref_a, pair.ref_b) if r is not None],
    }
