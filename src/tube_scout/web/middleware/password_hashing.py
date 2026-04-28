"""bcrypt password verification wrapper (T014/T028b).

Thin wrapper around :mod:`bcrypt` so route handlers depend on a stable
domain interface instead of bcrypt's evolving error surface (4.x → 5.x).
Malformed hashes raise :class:`BadHashError` rather than leaking the
underlying exception type.
"""

from __future__ import annotations

import bcrypt


class BadHashError(ValueError):
    """Raised when the stored hash is not a valid bcrypt hash."""


def verify_password(password: str, stored_hash: str) -> bool:
    """Return True iff ``password`` matches ``stored_hash``.

    Args:
        password: Plaintext password from the login form.
        stored_hash: bcrypt hash from the agenix-injected env var
            ``TUBE_SCOUT_ADMIN_PASSWORD_BCRYPT``.

    Returns:
        True on match, False on mismatch.

    Raises:
        ValueError: If either argument is empty (Constitution II).
        BadHashError: If ``stored_hash`` is not a valid bcrypt hash format.
    """
    if not password:
        raise ValueError("password must be a non-empty string")
    if not stored_hash:
        raise ValueError("stored_hash must be a non-empty string")
    try:
        return bcrypt.checkpw(password.encode("utf-8"), stored_hash.encode("utf-8"))
    except ValueError as exc:
        raise BadHashError(f"invalid bcrypt hash format: {exc}") from exc
