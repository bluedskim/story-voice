"""Simple in-memory rate limits (per client IP)."""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque


class RateLimiter:
    def __init__(self, max_events: int, window_sec: float) -> None:
        self.max_events = max_events
        self.window_sec = window_sec
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            q = self._events[key]
            while q and now - q[0] > self.window_sec:
                q.popleft()
            if len(q) >= self.max_events:
                return False
            q.append(now)
            return True
