"""Tests for tube_scout.web.middleware.rate_limit (T013 RED).

Covers:
- LoginRateLimiter.register_failure increments fail_count
- 5-failure threshold triggers a 5-minute lock (FR-004c)
- is_locked returns True until lock window passes
- register_success resets the counter
- Per-username isolation (one user lock does not affect another)
- Remaining-seconds helper for the Korean error message

Targets ``tube_scout.web.middleware.rate_limit`` — implementation pending (T028).
"""

from __future__ import annotations

import pytest


def test_initial_state_not_locked() -> None:
    from tube_scout.web.middleware import rate_limit

    limiter = rate_limit.LoginRateLimiter(now_fn=lambda: 1000)
    assert limiter.is_locked("ops") is False
    assert limiter.fail_count("ops") == 0


def test_register_failure_increments_count() -> None:
    from tube_scout.web.middleware import rate_limit

    limiter = rate_limit.LoginRateLimiter(now_fn=lambda: 1000)
    limiter.register_failure("ops")
    limiter.register_failure("ops")
    assert limiter.fail_count("ops") == 2
    assert limiter.is_locked("ops") is False


def test_five_failures_trigger_lock() -> None:
    from tube_scout.web.middleware import rate_limit

    now_holder = {"t": 1000}
    limiter = rate_limit.LoginRateLimiter(now_fn=lambda: now_holder["t"])
    for _ in range(5):
        limiter.register_failure("ops")
    assert limiter.is_locked("ops") is True


def test_lock_lasts_5_minutes() -> None:
    from tube_scout.web.middleware import rate_limit

    now_holder = {"t": 1000}
    limiter = rate_limit.LoginRateLimiter(now_fn=lambda: now_holder["t"])
    for _ in range(5):
        limiter.register_failure("ops")
    assert limiter.is_locked("ops") is True

    now_holder["t"] = 1000 + 5 * 60 - 1
    assert limiter.is_locked("ops") is True

    now_holder["t"] = 1000 + 5 * 60 + 1
    assert limiter.is_locked("ops") is False


def test_remaining_seconds_during_lock() -> None:
    from tube_scout.web.middleware import rate_limit

    now_holder = {"t": 1000}
    limiter = rate_limit.LoginRateLimiter(now_fn=lambda: now_holder["t"])
    for _ in range(5):
        limiter.register_failure("ops")

    now_holder["t"] = 1000 + 60  # 1 minute into lock
    remaining = limiter.remaining_lock_seconds("ops")
    assert remaining == 4 * 60


def test_register_success_resets_counter() -> None:
    from tube_scout.web.middleware import rate_limit

    limiter = rate_limit.LoginRateLimiter(now_fn=lambda: 1000)
    for _ in range(3):
        limiter.register_failure("ops")
    limiter.register_success("ops")
    assert limiter.fail_count("ops") == 0
    assert limiter.is_locked("ops") is False


def test_register_success_clears_lock() -> None:
    from tube_scout.web.middleware import rate_limit

    now_holder = {"t": 1000}
    limiter = rate_limit.LoginRateLimiter(now_fn=lambda: now_holder["t"])
    for _ in range(5):
        limiter.register_failure("ops")
    assert limiter.is_locked("ops") is True
    # Per spec FR-004c: success on the *next valid attempt* clears the lock.
    limiter.register_success("ops")
    assert limiter.is_locked("ops") is False


def test_per_username_isolation() -> None:
    from tube_scout.web.middleware import rate_limit

    limiter = rate_limit.LoginRateLimiter(now_fn=lambda: 1000)
    for _ in range(5):
        limiter.register_failure("ops")
    assert limiter.is_locked("ops") is True
    assert limiter.is_locked("admin") is False


def test_register_failure_rejects_empty_username() -> None:
    from tube_scout.web.middleware import rate_limit

    limiter = rate_limit.LoginRateLimiter(now_fn=lambda: 1000)
    with pytest.raises(ValueError):
        limiter.register_failure("")
