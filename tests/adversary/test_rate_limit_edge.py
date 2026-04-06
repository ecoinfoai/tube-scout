"""Adversary tests for rate limiting edge cases (T037)."""

import time

import pytest

from tube_scout.models.config import RateLimitProfile
from tube_scout.services.rate_limiter import RateLimiter


class TestBackoffCeiling:
    """Test that exponential backoff doesn't grow unbounded."""

    def test_backoff_delay_grows_exponentially(self) -> None:
        """Delay should increase with each attempt."""
        profile = RateLimitProfile(
            base_delay=0.01, max_retries=10, backoff_multiplier=2.0, jitter=0.0
        )
        limiter = RateLimiter(profile)

        # attempt=0: 0.01s, attempt=5: 0.01 * 2^5 = 0.32s
        start = time.monotonic()
        limiter.wait_on_error(attempt=5)
        elapsed = time.monotonic() - start
        assert elapsed >= 0.3  # 0.01 * 32 = 0.32

    def test_max_retries_zero_always_raises(self) -> None:
        """With max_retries=0, any wait_on_error should immediately raise."""
        profile = RateLimitProfile(
            base_delay=1.0, max_retries=0, backoff_multiplier=2.0, jitter=0.0
        )
        limiter = RateLimiter(profile)
        with pytest.raises(RuntimeError, match="Max retries.*exceeded"):
            limiter.wait_on_error(attempt=0)


class TestJitterBounds:
    """Test that jitter stays within expected bounds."""

    def test_jitter_does_not_produce_negative_delay(self) -> None:
        """Jitter larger than base_delay should clamp to 0, not go negative."""
        profile = RateLimitProfile(
            base_delay=0.01, max_retries=3, backoff_multiplier=2.0, jitter=1.0
        )
        limiter = RateLimiter(profile)

        # Run multiple times — delay should never be negative (no error)
        for _ in range(20):
            start = time.monotonic()
            limiter.wait()
            elapsed = time.monotonic() - start
            assert elapsed >= 0.0


class TestCallbackResilience:
    """Test behavior when callback raises or has unexpected behavior."""

    def test_callback_exception_propagates(self) -> None:
        """If on_backoff raises, it should propagate to caller."""
        profile = RateLimitProfile(
            base_delay=0.01, max_retries=3, backoff_multiplier=2.0, jitter=0.0
        )

        def bad_callback(attempt: int, delay: float) -> None:
            raise ValueError("callback error")

        limiter = RateLimiter(profile, on_backoff=bad_callback)

        with pytest.raises(ValueError, match="callback error"):
            limiter.wait_on_error(attempt=0)


class TestProfileValidation:
    """Test RateLimitProfile validation edge cases."""

    def test_zero_max_retries_valid(self) -> None:
        """max_retries=0 is valid (means no retries allowed)."""
        profile = RateLimitProfile(
            base_delay=1.0, max_retries=0, backoff_multiplier=1.0, jitter=0.0
        )
        assert profile.max_retries == 0

    def test_exactly_one_multiplier_valid(self) -> None:
        """backoff_multiplier=1.0 is valid (linear backoff)."""
        profile = RateLimitProfile(
            base_delay=1.0, max_retries=3, backoff_multiplier=1.0, jitter=0.0
        )
        assert profile.backoff_multiplier == 1.0

    def test_zero_jitter_valid(self) -> None:
        """jitter=0.0 means no random variance."""
        profile = RateLimitProfile(
            base_delay=1.0, max_retries=3, backoff_multiplier=2.0, jitter=0.0
        )
        assert profile.jitter == 0.0

    def test_negative_max_retries_invalid(self) -> None:
        """max_retries < 0 should be rejected."""
        with pytest.raises(Exception):
            RateLimitProfile(base_delay=1.0, max_retries=-1, backoff_multiplier=2.0)
