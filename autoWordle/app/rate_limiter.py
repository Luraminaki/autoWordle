#!/usr/bin/env python3
"""In-memory sliding-window rate limiter, keyed by an arbitrary string (client IP in practice).

Deliberately per-process, unlike `session_store.py`/`precompute_store.py`'s
SQLite-backed stores: a rate limiter's job is blunting abusive bursts, not
metering an exact global quota, so each `uvicorn` worker enforcing its own
independent budget is an acceptable trade for staying dependency-free and
avoiding a disk write on every single request. Running multiple workers
means the *effective* limit is `limit * worker_count`, not a hard cross-worker
guarantee - fine for this project's scale.

@author: Luraminaki
@rules: https://en.wikipedia.org/wiki/Wordle
"""

import time
from collections import defaultdict, deque
from threading import Lock


class RateLimiter:
    """A per-key sliding-window request rate limiter."""

    def __init__(self, limit: int, window_seconds: float) -> None:
        """Configure the limiter.

        Args:
            limit (int): Maximum allowed hits per key within `window_seconds`.
            window_seconds (float): Sliding window size, in seconds.
        """
        self.limit: int = limit
        self.window_seconds: float = window_seconds
        self.lock: Lock = Lock()
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        """Record a hit for `key` and report whether it's within the limit.

        Args:
            key (str): Identifies the caller (typically a client IP).

        Returns:
            bool: `True` if this hit is allowed (and is now recorded),
            `False` if `key` is already at its limit within the window (the
            hit is not recorded).
        """
        now = time.time()

        with self.lock:
            hits = self._hits[key]
            while hits and (now - hits[0]) > self.window_seconds:
                hits.popleft()

            if len(hits) >= self.limit:
                return False

            hits.append(now)
            return True
