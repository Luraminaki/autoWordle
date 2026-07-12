#!/usr/bin/env python3
"""Unit tests for `autoWordle.app.rate_limiter.RateLimiter`."""

#===================================================================================================
import pytest

from autoWordle.app import rate_limiter

#===================================================================================================


def test_allow_under_limit_returns_true() -> None:
    limiter = rate_limiter.RateLimiter(limit=3, window_seconds=60.0)

    assert limiter.allow('client-a') is True
    assert limiter.allow('client-a') is True
    assert limiter.allow('client-a') is True


def test_allow_blocks_once_limit_reached() -> None:
    limiter = rate_limiter.RateLimiter(limit=2, window_seconds=60.0)

    assert limiter.allow('client-a') is True
    assert limiter.allow('client-a') is True
    assert limiter.allow('client-a') is False


def test_allow_tracks_keys_independently() -> None:
    limiter = rate_limiter.RateLimiter(limit=1, window_seconds=60.0)

    assert limiter.allow('client-a') is True
    assert limiter.allow('client-b') is True  # a different key, unaffected by client-a's budget
    assert limiter.allow('client-a') is False
    assert limiter.allow('client-b') is False


def test_allow_window_slides(monkeypatch: pytest.MonkeyPatch) -> None:
    limiter = rate_limiter.RateLimiter(limit=1, window_seconds=10.0)
    now = [1000.0]
    monkeypatch.setattr(rate_limiter.time, 'time', lambda: now[0])

    assert limiter.allow('client-a') is True
    assert limiter.allow('client-a') is False  # still within the 10s window

    now[0] += 10.1  # window has fully elapsed
    assert limiter.allow('client-a') is True


def test_abandoned_keys_are_swept_after_a_window(monkeypatch: pytest.MonkeyPatch) -> None:
    # Regression test: a key that makes one request and never returns used to
    # leave a permanent dict entry for the life of the process - only a key
    # that gets looked up again ever had its own deque trimmed.
    now = [1000.0]
    monkeypatch.setattr(rate_limiter.time, 'time', lambda: now[0])
    limiter = rate_limiter.RateLimiter(limit=5, window_seconds=10.0)

    assert limiter.allow('client-a') is True
    assert 'client-a' in limiter._hits

    # A different key's call, well past client-a's window, is what actually
    # triggers the sweep - client-a itself is never looked up again.
    now[0] += 10.1
    assert limiter.allow('client-b') is True

    assert 'client-a' not in limiter._hits
    assert 'client-b' in limiter._hits


def test_sweep_does_not_remove_keys_still_within_their_window(monkeypatch: pytest.MonkeyPatch) -> None:
    now = [1000.0]
    monkeypatch.setattr(rate_limiter.time, 'time', lambda: now[0])
    limiter = rate_limiter.RateLimiter(limit=5, window_seconds=10.0)

    assert limiter.allow('client-a') is True  # now=1000.0

    now[0] += 9.0  # not due for a sweep yet (9 < 10)
    assert limiter.allow('client-a') is True  # client-a hits again, refreshing its last-hit timestamp to 1009.0

    now[0] += 2.0  # now=1011.0 - a sweep is now due (11 >= 10 since construction)
    assert limiter.allow('client-b') is True  # triggers it

    # client-a's most recent hit is only 2s old at this point - well within its own 10s window, so not swept.
    assert 'client-a' in limiter._hits
