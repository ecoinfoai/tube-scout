"""Per-service rate limiting with exponential backoff for tube-scout.

Provides RateLimiter class that manages inter-request delays and
error-triggered exponential backoff with configurable profiles for
different YouTube API services (transcript scraping vs Data API).
"""

import random
import time
from collections.abc import Callable

from tube_scout.models.config import RateLimitProfile


class RateLimiter:
    """Rate limiter with inter-request delay and exponential backoff.

    Args:
        profile: Rate limiting configuration profile.
        on_backoff: Optional callback invoked on error backoff with
            (attempt: int, delay: float) arguments.

    Raises:
        TypeError: If profile is not a RateLimitProfile instance.
    """

    def __init__(
        self,
        profile: RateLimitProfile,
        on_backoff: Callable[[int, float], None] | None = None,
    ) -> None:
        if not isinstance(profile, RateLimitProfile):
            raise TypeError(
                f"profile must be a RateLimitProfile, got {type(profile).__name__}"
            )
        self.profile = profile
        self._on_backoff = on_backoff

    def wait(self) -> None:
        """Sleep for base_delay with optional jitter between requests."""
        delay = self.profile.base_delay
        if self.profile.jitter > 0:
            delay += random.uniform(-self.profile.jitter, self.profile.jitter)
        delay = max(0.0, delay)
        if delay > 0:
            time.sleep(delay)

    def wait_on_error(self, attempt: int) -> None:
        """Apply exponential backoff after an error.

        Args:
            attempt: Zero-based attempt number (0 = first retry).

        Raises:
            RuntimeError: If attempt >= max_retries.
        """
        if attempt >= self.profile.max_retries:
            raise RuntimeError(
                f"Max retries ({self.profile.max_retries}) exceeded "
                f"at attempt {attempt}"
            )
        delay = self.profile.base_delay * (self.profile.backoff_multiplier**attempt)
        if self.profile.jitter > 0:
            delay += random.uniform(-self.profile.jitter, self.profile.jitter)
        delay = max(0.0, delay)

        if self._on_backoff is not None:
            self._on_backoff(attempt, delay)

        if delay > 0:
            time.sleep(delay)
