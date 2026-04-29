"""In-memory login rate limiter (T028).

Single-user threat model + Constitution V (no Redis): a process-local dict
keyed by username tracks failures and lock expiry. State is intentionally
volatile — process restart resets attempts (data-model.md §7).

Spec FR-004c: 5 consecutive failures lock for 5 minutes; success clears the
lock immediately.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

LOCK_THRESHOLD: int = 5
"""Failures required to trigger a lock."""

LOCK_WINDOW_SECONDS: int = 5 * 60
"""Lock window duration in seconds."""


@dataclass
class _Attempt:
    """Per-username attempt counter."""

    fail_count: int = 0
    locked_until: int | None = None  # Unix epoch seconds


class LoginRateLimiter:
    """Track login failures and apply a 5-attempts/5-minutes lockout.

    Args:
        now_fn: Override clock source. Defaults to ``time.time`` at import.
            Tests inject a deterministic clock to avoid ``time.sleep``.
    """

    def __init__(self, now_fn: Callable[[], float] | None = None) -> None:
        if now_fn is None:
            import time

            now_fn = time.time
        self._now_fn = now_fn
        self._state: dict[str, _Attempt] = {}

    def _now(self) -> int:
        return int(self._now_fn())

    def _entry(self, username: str) -> _Attempt:
        return self._state.setdefault(username, _Attempt())

    def fail_count(self, username: str) -> int:
        """Return the current consecutive-failure count for ``username``."""
        if not username:
            raise ValueError("username must be a non-empty string")
        return self._state.get(username, _Attempt()).fail_count

    def is_locked(self, username: str) -> bool:
        """Return True iff ``username`` is currently within a lock window."""
        if not username:
            raise ValueError("username must be a non-empty string")
        entry = self._state.get(username)
        if entry is None or entry.locked_until is None:
            return False
        if self._now() > entry.locked_until:
            return False
        return True

    def remaining_lock_seconds(self, username: str) -> int:
        """Return remaining lock seconds (>= 0) or 0 when unlocked."""
        if not username:
            raise ValueError("username must be a non-empty string")
        entry = self._state.get(username)
        if entry is None or entry.locked_until is None:
            return 0
        remaining = entry.locked_until - self._now()
        return max(0, remaining)

    def register_failure(self, username: str) -> None:
        """Increment the failure counter; lock when threshold is hit.

        ADV-US1-81: if a prior lock window has already expired the counter
        is reset so the next failure starts a fresh window. Without the
        reset, a user who hits 5 failures, waits 5 minutes, then fails once
        would be immediately re-locked (fail_count would already be ≥ 5).
        """
        if not username:
            raise ValueError("username must be a non-empty string")
        entry = self._entry(username)
        if entry.locked_until is not None and entry.locked_until <= self._now():
            entry.fail_count = 0
            entry.locked_until = None
        entry.fail_count += 1
        if entry.fail_count >= LOCK_THRESHOLD:
            entry.locked_until = self._now() + LOCK_WINDOW_SECONDS

    def register_success(self, username: str) -> None:
        """Reset the counter and clear any active lock."""
        if not username:
            raise ValueError("username must be a non-empty string")
        if username in self._state:
            del self._state[username]
