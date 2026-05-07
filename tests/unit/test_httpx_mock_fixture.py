"""Smoke test for httpx_mock fixture via pytest-httpx (T003)."""

import httpx
from pytest_httpx import HTTPXMock

from tests.fixtures.httpx_mock import (
    device_code_response,
    token_access_denied_response,
    token_expired_response,
    token_pending_response,
    token_slow_down_response,
    token_success_response,
)


def test_httpx_mock_post_returns_expected_payload(httpx_mock: HTTPXMock) -> None:
    """httpx_mock intercepts POST and returns mocked response."""
    httpx_mock.add_response(
        method="POST",
        url="https://oauth2.googleapis.com/token",
        json={"access_token": "ya29.test", "token_type": "Bearer"},
    )
    response = httpx.post(
        "https://oauth2.googleapis.com/token",
        data={"grant_type": "urn:ietf:params:oauth:grant-type:device_code"},
    )
    assert response.status_code == 200
    assert response.json()["access_token"] == "ya29.test"


def test_device_code_response_builder() -> None:
    """device_code_response builds correct RFC 8628 §3.2 payload."""
    resp = device_code_response(device_code="dc-001", user_code="ABCD-1234")
    assert resp["status_code"] == 200
    body = resp["json"]
    assert body["device_code"] == "dc-001"
    assert body["user_code"] == "ABCD-1234"
    assert "verification_url" in body
    assert "expires_in" in body
    assert "interval" in body


def test_token_success_response_builder() -> None:
    """token_success_response builds correct token payload."""
    resp = token_success_response(access_token="ya29.abc")
    assert resp["status_code"] == 200
    assert resp["json"]["access_token"] == "ya29.abc"
    assert resp["json"]["token_type"] == "Bearer"


def test_token_error_response_builders() -> None:
    """Error response builders return correct RFC 8628 §3.5 error codes."""
    assert token_pending_response()["json"]["error"] == "authorization_pending"
    assert token_slow_down_response()["json"]["error"] == "slow_down"
    assert token_expired_response()["json"]["error"] == "expired_token"
    assert token_access_denied_response()["json"]["error"] == "access_denied"
