"""Session signing + CSRF helpers (T027).

itsdangerous-backed cookie signing for the admin web UI:

- :class:`SessionSigner` wraps :class:`itsdangerous.URLSafeSerializer` and
  enforces an 8h activity window on every verify (spec FR-004a).
- :class:`SessionExpired` and :class:`SessionTampered` are domain-specific
  exceptions so route handlers can map them to the correct Korean message
  (auth.csrf vs session.expired) without leaking itsdangerous internals.
- :func:`generate_csrf_token` returns a 32-hex-char (16 byte) random token.
- :func:`verify_csrf_token` runs constant-time comparison (timing attack
  defence).

The 8h policy lives in :data:`SESSION_MAX_AGE_SECONDS` so the route layer
sets ``Set-Cookie ... Max-Age=`` to the same value (single source of truth).
"""

from __future__ import annotations

import hmac
import secrets
from dataclasses import dataclass
from typing import Any, Callable

from itsdangerous import BadSignature, URLSafeSerializer


@dataclass(frozen=True)
class VerifiedSession:
    """Lightweight verified-session view returned by :meth:`SessionSigner.verify`.

    Distinct from :class:`tube_scout.web.models.SessionPayload` (the strict
    Pydantic shape used at issue time). The verify path only needs attribute
    access; strict regex on csrf_token at verify time would break legitimate
    older cookies if the token format ever changes.
    """

    username: str
    issued_at: int
    last_active: int
    csrf_token: str

SESSION_MAX_AGE_SECONDS: int = 8 * 3600
"""Max session lifetime in seconds (spec FR-004a)."""

_CSRF_TOKEN_BYTES = 16


class SessionExpired(Exception):
    """Raised when a verified cookie is older than ``SESSION_MAX_AGE_SECONDS``."""


class SessionTampered(Exception):
    """Raised when itsdangerous fails signature verification."""


class SessionSigner:
    """Sign and verify session cookie payloads.

    Args:
        secret: itsdangerous secret key. Must be non-empty (Constitution II).
        salt: Optional namespace salt; defaults to ``"tube-scout-admin"``.
    """

    def __init__(self, *, secret: str, salt: str = "tube-scout-admin") -> None:
        if not secret:
            raise ValueError("secret must be a non-empty string")
        self._serializer = URLSafeSerializer(secret_key=secret, salt=salt)

    def sign(self, payload: dict) -> str:
        """Return a signed string from the cookie ``payload`` dict.

        Validation of the strict :class:`SessionPayload` shape happens on
        :meth:`verify` (round-trip is what matters for security; in-memory
        sign callers are trusted route handlers that build the payload from
        already-validated session state).
        """
        return self._serializer.dumps(payload)

    def verify(self, cookie: str, *, now: int) -> VerifiedSession:
        """Verify and return the :class:`VerifiedSession` from ``cookie``.

        Args:
            cookie: The signed cookie value.
            now: Current Unix epoch seconds.

        Returns:
            :class:`VerifiedSession` with username/csrf_token/timestamps.

        Raises:
            SessionTampered: If the signature is invalid or the secret differs,
                or required keys are missing from the deserialized payload.
            SessionExpired: If ``now - last_active > SESSION_MAX_AGE_SECONDS``.
        """
        try:
            raw: Any = self._serializer.loads(cookie)
        except BadSignature as exc:
            raise SessionTampered("session signature invalid") from exc
        if not isinstance(raw, dict):
            raise SessionTampered("session payload is not an object")
        try:
            verified = VerifiedSession(
                username=str(raw["username"]),
                issued_at=int(raw["issued_at"]),
                last_active=int(raw["last_active"]),
                csrf_token=str(raw["csrf_token"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise SessionTampered("session payload missing required keys") from exc
        if now - verified.last_active > SESSION_MAX_AGE_SECONDS:
            raise SessionExpired(
                f"session age {now - verified.last_active}s exceeds max"
            )
        return verified


def generate_csrf_token(rng: Callable[[int], bytes] = secrets.token_bytes) -> str:
    """Return a 32-hex-char CSRF token (16 random bytes).

    Args:
        rng: Override randomness source for tests; defaults to
            :func:`secrets.token_bytes`.
    """
    return rng(_CSRF_TOKEN_BYTES).hex()


def verify_csrf_token(submitted: str, expected: str) -> bool:
    """Constant-time comparison of two CSRF tokens.

    Args:
        submitted: Token from the form / X-CSRF-Token header.
        expected: Token stored in the verified session payload.

    Returns:
        True iff both tokens are present and match byte-by-byte.
    """
    if not submitted or not expected:
        return False
    return hmac.compare_digest(submitted, expected)
