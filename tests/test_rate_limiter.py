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
