"""httpx mock helpers for spec 009 contract tests.

pytest-httpx provides the ``httpx_mock`` fixture automatically via its plugin.
This module re-exports the type for annotations and provides response builder
helpers for Google OAuth 2.0 device-code flow endpoints (R1, RFC 8628).
"""

from __future__ import annotations

import json

import httpx
from pytest_httpx import HTTPXMock

__all__ = [
    "HTTPXMock",
    "device_code_response",
    "token_success_response",
    "token_pending_response",
    "token_slow_down_response",
    "token_expired_response",
    "token_access_denied_response",
]

DEVICE_AUTH_URL = "https://oauth2.googleapis.com/device/code"
TOKEN_URL = "https://oauth2.googleapis.com/token"


def device_code_response(
    device_code: str = "test-device-code",
    user_code: str = "TEST-CODE",
    verification_url: str = "https://www.google.com/device",
    expires_in: int = 1800,
    interval: int = 5,
) -> httpx.Response:
    """Build a successful device authorization response (RFC 8628 §3.2)."""
    return httpx.Response(
        200,
        json={
            "device_code": device_code,
            "user_code": user_code,
            "verification_url": verification_url,
            "expires_in": expires_in,
            "interval": interval,
        },
    )


def token_success_response(
    access_token: str = "ya29.test-access-token",
    refresh_token: str = "1//test-refresh-token",
    expires_in: int = 3600,
    scope: str = "https://www.googleapis.com/auth/youtube.readonly",
) -> httpx.Response:
    """Build a successful token response (RFC 8628 §3.5)."""
    return httpx.Response(
        200,
        json={
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_in": expires_in,
            "token_type": "Bearer",
            "scope": scope,
        },
    )


def token_pending_response() -> httpx.Response:
    """Build an authorization_pending polling response (RFC 8628 §3.5 / Google: HTTP 400)."""
    return httpx.Response(
        400,
        json={"error": "authorization_pending"},
    )


def token_slow_down_response() -> httpx.Response:
    """Build a slow_down polling response (RFC 8628 §3.5 / Google: HTTP 400)."""
    return httpx.Response(
        400,
        json={"error": "slow_down"},
    )


def token_expired_response() -> httpx.Response:
    """Build an expired_token response (RFC 8628 §3.5 / Google: HTTP 400)."""
    return httpx.Response(
        400,
        json={"error": "expired_token"},
    )


def token_access_denied_response() -> httpx.Response:
    """Build an access_denied response (RFC 8628 §3.5 / Google: HTTP 400)."""
    return httpx.Response(
        400,
        json={"error": "access_denied"},
    )
