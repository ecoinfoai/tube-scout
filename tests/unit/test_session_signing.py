"""Tests for tube_scout.web.middleware.session (T012 RED).

Covers:
- itsdangerous-based payload signing + verification roundtrip
- 8h expiration boundary (spec FR-004a)
- Tamper detection (BadSignature on payload mutation)
- Tamper detection on signature mutation
- CSRF token issuance + constant-time verification
- Cookie max-age aligns with the 8h policy

Targets ``tube_scout.web.middleware.session`` — implementation pending (T027).
"""

from __future__ import annotations

import time

import pytest


SECRET = "test-secret-do-not-use-in-prod"


def test_sign_then_verify_roundtrip() -> None:
    from tube_scout.web.middleware import session

    signer = session.SessionSigner(secret=SECRET)
    now = int(time.time())
    payload = {
        "username": "ops",
        "issued_at": now,
        "last_active": now,
        "csrf_token": "abc123",
    }
    cookie = signer.sign(payload)
    assert isinstance(cookie, str)
    decoded = signer.verify(cookie, now=now + 60)
    assert decoded.username == "ops"
    assert decoded.csrf_token == "abc123"


def test_verify_rejects_expired_session() -> None:
    from tube_scout.web.middleware import session

    signer = session.SessionSigner(secret=SECRET)
    issued = int(time.time())
    cookie = signer.sign(
        {
            "username": "ops",
            "issued_at": issued,
            "last_active": issued,
            "csrf_token": "abc",
        }
    )
    eight_hours_plus_one = issued + 8 * 3600 + 1
    with pytest.raises(session.SessionExpired):
        signer.verify(cookie, now=eight_hours_plus_one)


def test_verify_accepts_session_within_8h() -> None:
    from tube_scout.web.middleware import session

    signer = session.SessionSigner(secret=SECRET)
    issued = int(time.time())
    cookie = signer.sign(
        {
            "username": "ops",
            "issued_at": issued,
            "last_active": issued,
            "csrf_token": "abc",
        }
    )
    just_under_8h = issued + 8 * 3600 - 1
    decoded = signer.verify(cookie, now=just_under_8h)
    assert decoded.username == "ops"


def test_verify_rejects_payload_tamper() -> None:
    from tube_scout.web.middleware import session

    signer = session.SessionSigner(secret=SECRET)
    cookie = signer.sign(
        {
            "username": "ops",
            "issued_at": 1,
            "last_active": 1,
            "csrf_token": "abc",
        }
    )
    # Flip a character mid-cookie
    tampered = cookie[:-3] + "XXX"
    with pytest.raises(session.SessionTampered):
        signer.verify(tampered, now=2)


def test_verify_rejects_wrong_secret() -> None:
    from tube_scout.web.middleware import session

    signer_a = session.SessionSigner(secret=SECRET)
    signer_b = session.SessionSigner(secret="different-secret")
    cookie = signer_a.sign(
        {
            "username": "ops",
            "issued_at": 1,
            "last_active": 1,
            "csrf_token": "abc",
        }
    )
    with pytest.raises(session.SessionTampered):
        signer_b.verify(cookie, now=2)


def test_csrf_token_is_random_hex_16_bytes() -> None:
    from tube_scout.web.middleware import session

    a = session.generate_csrf_token()
    b = session.generate_csrf_token()
    assert a != b
    assert len(a) == 32  # 16 bytes hex
    assert all(c in "0123456789abcdef" for c in a)


def test_csrf_verify_constant_time_match() -> None:
    from tube_scout.web.middleware import session

    token = session.generate_csrf_token()
    assert session.verify_csrf_token(token, token) is True
    assert session.verify_csrf_token(token, "0" * 32) is False


def test_signer_rejects_empty_secret() -> None:
    from tube_scout.web.middleware import session

    with pytest.raises(ValueError):
        session.SessionSigner(secret="")


def test_session_max_age_seconds_constant() -> None:
    from tube_scout.web.middleware import session

    assert session.SESSION_MAX_AGE_SECONDS == 8 * 3600
