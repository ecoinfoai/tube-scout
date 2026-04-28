"""Tests for tube_scout.web.middleware.password_hashing (T014 RED).

Covers:
- bcrypt.checkpw verifies a known good password against its stored hash
- Wrong password is rejected (no false-positive)
- Malformed hash raises a domain error (BadHashError) instead of leaking
  bcrypt internals to the caller
- Empty password / hash → ValueError (Constitution II Fail-Fast)
- API works against a bcrypt 5.x hash (declared 4.1, locked 5.0 — verify the
  5.x hash format is accepted by checkpw the same as 4.x)

Targets ``tube_scout.web.middleware.password_hashing`` — implementation
pending (T027/T028 area, packaged separately for testability).
"""

from __future__ import annotations

import bcrypt
import pytest

# Generated once at module load with bcrypt 5.x; format ``$2b$12$...``.
PLAIN = "S3cure!Pass-2026"
KNOWN_HASH = bcrypt.hashpw(PLAIN.encode(), bcrypt.gensalt(rounds=4)).decode()


def test_verify_password_accepts_correct_password() -> None:
    from tube_scout.web.middleware import password_hashing

    assert password_hashing.verify_password(PLAIN, KNOWN_HASH) is True


def test_verify_password_rejects_wrong_password() -> None:
    from tube_scout.web.middleware import password_hashing

    assert password_hashing.verify_password("wrong-password", KNOWN_HASH) is False


def test_verify_password_rejects_subtly_wrong_password() -> None:
    from tube_scout.web.middleware import password_hashing

    assert password_hashing.verify_password(PLAIN + " ", KNOWN_HASH) is False


def test_malformed_hash_raises_bad_hash_error() -> None:
    from tube_scout.web.middleware import password_hashing

    with pytest.raises(password_hashing.BadHashError):
        password_hashing.verify_password(PLAIN, "not-a-bcrypt-hash")


def test_empty_password_rejected() -> None:
    from tube_scout.web.middleware import password_hashing

    with pytest.raises(ValueError):
        password_hashing.verify_password("", KNOWN_HASH)


def test_empty_hash_rejected() -> None:
    from tube_scout.web.middleware import password_hashing

    with pytest.raises(ValueError):
        password_hashing.verify_password(PLAIN, "")


def test_bcrypt_5x_hash_format_compatible() -> None:
    """Spec lock pinned bcrypt 5.0 while pyproject declares 4.1. Confirm the
    $2b$ prefix produced by 5.x is still verified by our wrapper, and that
    the wrapper itself does not depend on a specific bcrypt version surface."""
    from tube_scout.web.middleware import password_hashing

    assert KNOWN_HASH.startswith("$2b$")
    assert password_hashing.verify_password(PLAIN, KNOWN_HASH) is True
