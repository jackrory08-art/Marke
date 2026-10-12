"""In-memory ring buffer of recent log records for the Logs screen."""

import logging
from collections import deque
from datetime import datetime, timezone
from typing import Optional


class RingBufferHandler(logging.Handler):
    def __init__(self, capacity: int = 1000, level: int = logging.INFO):
        super().__init__(level)
        self._records: deque = deque(maxlen=capacity)
        self._seq = 0

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._seq += 1
            self._records.append({
                "id": self._seq,
                "ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
                "level": record.levelname,
                "logger": record.name,
                "message": record.getMessage()[:2000],
            })
        except Exception:  # never let logging break the app
            pass

    def recent(self, limit: int = 200, min_level: Optional[str] = None) -> list[dict]:
        items = list(self._records)
        if min_level:
            floor = logging.getLevelName(min_level.upper())
            if isinstance(floor, int):
                items = [r for r in items if logging.getLevelName(r["level"]) >= floor]
        return items[-max(1, min(limit, 1000)):][::-1]
