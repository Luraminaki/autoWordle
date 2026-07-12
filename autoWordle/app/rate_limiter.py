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
        self._last_sweep: float = time.time()

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
            self._sweep_if_due(now)

            hits = self._hits[key]
            while hits and (now - hits[0]) > self.window_seconds:
                hits.popleft()

            if len(hits) >= self.limit:
                return False

            hits.append(now)
            return True

    def _sweep_if_due(self, now: float) -> None:
        """Drop entries for keys that haven't made a request in over a window.

        A key's deque is only ever trimmed when *that same key* is looked up
        again in `allow()` - a key that stops making requests entirely (the
        common case for a rate limiter: most callers hit it once and never
        return) is never looked up again to trigger that, so without this,
        `self._hits` would grow by one permanent entry per distinct key ever
        seen, for the life of the process. Runs at most once per
        `window_seconds`, amortizing the O(total keys) sweep cost instead of
        paying it on every single call. Caller must already hold `self.lock`.
        """
        if (now - self._last_sweep) < self.window_seconds:
            return

        stale_keys = [key for key, hits in self._hits.items() if not hits or (now - hits[-1]) > self.window_seconds]
        for key in stale_keys:
            del self._hits[key]

        self._last_sweep = now
