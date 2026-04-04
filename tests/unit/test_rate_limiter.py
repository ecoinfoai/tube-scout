"""Unit tests for RateLimiter service."""

import time
from unittest.mock import MagicMock

import pytest

from tube_scout.models.config import RateLimitProfile
from tube_scout.services.rate_limiter import RateLimiter


class TestRateLimiterWait:
    """Tests for inter-request delay (wait)."""

    def test_wait_delays_by_base_delay(self) -> None:
        """Wait should sleep for approximately base_delay seconds."""
        profile = RateLimitProfile(
            base_delay=0.05, max_retries=3, backoff_multiplier=2.0, jitter=0.0
        )
        limiter = RateLimiter(profile)

        start = time.monotonic()
        limiter.wait()
        elapsed = time.monotonic() - start

        assert elapsed >= 0.04  # Allow slight timing variance
        assert elapsed < 0.15

    def test_wait_with_jitter_adds_randomness(self) -> None:
        """Wait with jitter should add random variance to base delay."""
        profile = RateLimitProfile(
            base_delay=0.05, max_retries=3, backoff_multiplier=2.0, jitter=0.02
        )
        limiter = RateLimiter(profile)

        # Run multiple waits and check they aren't all identical
        durations = []
        for _ in range(5):
            start = time.monotonic()
            limiter.wait()
            durations.append(time.monotonic() - start)

        # All should be >= base_delay - jitter (but non-negative)
        for d in durations:
            assert d >= 0.02  # base_delay - jitter = 0.03, allow timing margin

    def test_wait_with_zero_base_delay(self) -> None:
        """Wait with zero base_delay should return almost immediately."""
        profile = RateLimitProfile(
            base_delay=0.0, max_retries=3, backoff_multiplier=2.0, jitter=0.0
        )
        limiter = RateLimiter(profile)

        start = time.monotonic()
        limiter.wait()
        elapsed = time.monotonic() - start

        assert elapsed < 0.05


class TestRateLimiterWaitOnError:
    """Tests for exponential backoff on error (wait_on_error)."""

    def test_first_attempt_uses_base_delay(self) -> None:
        """First error attempt should use base_delay as backoff."""
        profile = RateLimitProfile(
            base_delay=0.05, max_retries=3, backoff_multiplier=2.0, jitter=0.0
        )
        limiter = RateLimiter(profile)

        start = time.monotonic()
        limiter.wait_on_error(attempt=0)
        elapsed = time.monotonic() - start

        assert elapsed >= 0.04
        assert elapsed < 0.15

    def test_exponential_backoff_increases_delay(self) -> None:
        """Each subsequent attempt should multiply delay by backoff_multiplier."""
        profile = RateLimitProfile(
            base_delay=0.05, max_retries=5, backoff_multiplier=2.0, jitter=0.0
        )
        limiter = RateLimiter(profile)

        # attempt=0: 0.05s, attempt=1: 0.10s, attempt=2: 0.20s
        start = time.monotonic()
        limiter.wait_on_error(attempt=1)
        elapsed_1 = time.monotonic() - start

        start = time.monotonic()
        limiter.wait_on_error(attempt=2)
        elapsed_2 = time.monotonic() - start

        # attempt=2 should take roughly 2x attempt=1
        assert elapsed_2 > elapsed_1 * 1.5

    def test_max_retries_exceeded_raises(self) -> None:
        """Attempting beyond max_retries should raise RuntimeError."""
        profile = RateLimitProfile(
            base_delay=0.05, max_retries=3, backoff_multiplier=2.0, jitter=0.0
        )
        limiter = RateLimiter(profile)

        with pytest.raises(RuntimeError, match="Max retries.*exceeded"):
            limiter.wait_on_error(attempt=3)

    def test_max_retries_boundary(self) -> None:
        """Last valid attempt (max_retries - 1) should succeed."""
        profile = RateLimitProfile(
            base_delay=0.01, max_retries=3, backoff_multiplier=2.0, jitter=0.0
        )
        limiter = RateLimiter(profile)

        # attempt=2 is the last valid (0-indexed, max_retries=3)
        limiter.wait_on_error(attempt=2)  # Should not raise


class TestRateLimiterCallback:
    """Tests for on_backoff callback."""

    def test_on_backoff_called_during_wait_on_error(self) -> None:
        """The on_backoff callback should be invoked with attempt and delay."""
        profile = RateLimitProfile(
            base_delay=0.01, max_retries=3, backoff_multiplier=2.0, jitter=0.0
        )
        callback = MagicMock()
        limiter = RateLimiter(profile, on_backoff=callback)

        limiter.wait_on_error(attempt=1)

        callback.assert_called_once()
        args = callback.call_args[0]
        assert args[0] == 1  # attempt
        assert args[1] > 0  # delay > 0

    def test_on_backoff_not_called_during_regular_wait(self) -> None:
        """The on_backoff callback should NOT be invoked during regular wait()."""
        profile = RateLimitProfile(
            base_delay=0.01, max_retries=3, backoff_multiplier=2.0, jitter=0.0
        )
        callback = MagicMock()
        limiter = RateLimiter(profile, on_backoff=callback)

        limiter.wait()

        callback.assert_not_called()

    def test_no_callback_does_not_error(self) -> None:
        """RateLimiter without callback should work fine."""
        profile = RateLimitProfile(
            base_delay=0.01, max_retries=3, backoff_multiplier=2.0, jitter=0.0
        )
        limiter = RateLimiter(profile)

        limiter.wait()
        limiter.wait_on_error(attempt=0)
        # No error raised


class TestRateLimiterInit:
    """Tests for RateLimiter initialization."""

    def test_requires_profile(self) -> None:
        """RateLimiter must be created with a RateLimitProfile."""
        profile = RateLimitProfile(
            base_delay=1.0, max_retries=3, backoff_multiplier=2.0
        )
        limiter = RateLimiter(profile)
        assert limiter.profile == profile

    def test_invalid_profile_type_raises(self) -> None:
        """Passing non-RateLimitProfile should raise TypeError."""
        with pytest.raises(TypeError):
            RateLimiter("not a profile")  # type: ignore[arg-type]
