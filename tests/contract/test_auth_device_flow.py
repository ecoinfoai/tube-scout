"""RED contract tests for OAuth 2.0 Device Authorization Grant (T008).

Tests the auth_device_flow module against Google OAuth endpoints using
httpx_mock. All tests MUST fail (ImportError / AttributeError) until T014
implements src/tube_scout/services/auth_device_flow.py.

Contract source: specs/009-runtime-auth-fix/contracts/auth_flow.md
RFC 8628 §3.2, §3.5
"""

from __future__ import annotations

import pytest
from pytest_httpx import HTTPXMock

from tests.fixtures.httpx_mock import (
    device_code_response,
    token_access_denied_response,
    token_expired_response,
    token_pending_response,
    token_slow_down_response,
    token_success_response,
)

DEVICE_AUTH_URL = "https://oauth2.googleapis.com/device/code"
TOKEN_URL = "https://oauth2.googleapis.com/token"

CLIENT_ID = "test-client-id"
CLIENT_SECRET = "test-client-secret"


@pytest.fixture
def device_flow():
    """Import DeviceFlow lazily so RED tests fail with ImportError, not NameError."""
    from tube_scout.services.auth_device_flow import DeviceFlow  # noqa: PLC0415

    return DeviceFlow(client_id=CLIENT_ID, client_secret=CLIENT_SECRET)


class TestDeviceFlowSuccess:
    def test_fetch_device_code_returns_code_and_url(
        self, device_flow, httpx_mock: HTTPXMock
    ) -> None:
        httpx_mock.add_response(
            url=DEVICE_AUTH_URL, method="POST", **device_code_response()
        )
        result = device_flow.fetch_device_code(
            scopes=["https://www.googleapis.com/auth/youtube.readonly"]
        )
        assert result["device_code"] == "test-device-code"
        assert result["user_code"] == "TEST-CODE"
        assert "verification_url" in result
        assert result["interval"] == 5

    def test_poll_token_success_returns_token_dict(
        self, device_flow, httpx_mock: HTTPXMock
    ) -> None:
        httpx_mock.add_response(
            url=TOKEN_URL, method="POST", **token_success_response()
        )
        token = device_flow.poll_token(
            device_code="test-device-code",
            interval=0,
            expires_in=60,
        )
        assert token["access_token"] == "ya29.test-access-token"
        assert token["refresh_token"] == "1//test-refresh-token"
        assert token["token_type"] == "Bearer"

    def test_run_success_path(self, device_flow, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=DEVICE_AUTH_URL, method="POST", **device_code_response()
        )
        httpx_mock.add_response(
            url=TOKEN_URL, method="POST", **token_success_response()
        )
        token = device_flow.run(
            scopes=["https://www.googleapis.com/auth/youtube.readonly"],
            on_code=lambda code, url, expires: None,
        )
        assert token["access_token"] == "ya29.test-access-token"


class TestDeviceFlowPendingThenSuccess:
    def test_pending_then_success(self, device_flow, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=DEVICE_AUTH_URL, method="POST", **device_code_response(interval=0)
        )
        httpx_mock.add_response(
            url=TOKEN_URL, method="POST", **token_pending_response()
        )
        httpx_mock.add_response(
            url=TOKEN_URL, method="POST", **token_success_response()
        )
        token = device_flow.run(
            scopes=["https://www.googleapis.com/auth/youtube.readonly"],
            on_code=lambda code, url, expires: None,
        )
        assert token["access_token"] == "ya29.test-access-token"

    def test_multiple_pending_then_success(
        self, device_flow, httpx_mock: HTTPXMock
    ) -> None:
        httpx_mock.add_response(
            url=DEVICE_AUTH_URL, method="POST", **device_code_response(interval=0)
        )
        for _ in range(3):
            httpx_mock.add_response(
                url=TOKEN_URL, method="POST", **token_pending_response()
            )
        httpx_mock.add_response(
            url=TOKEN_URL, method="POST", **token_success_response()
        )
        token = device_flow.run(
            scopes=["https://www.googleapis.com/auth/youtube.readonly"],
            on_code=lambda code, url, expires: None,
        )
        assert token["access_token"] == "ya29.test-access-token"


class TestDeviceFlowSlowDown:
    def test_slow_down_increases_interval_then_success(
        self, device_flow, httpx_mock: HTTPXMock
    ) -> None:
        httpx_mock.add_response(
            url=DEVICE_AUTH_URL, method="POST", **device_code_response(interval=0)
        )
        httpx_mock.add_response(
            url=TOKEN_URL, method="POST", **token_slow_down_response()
        )
        httpx_mock.add_response(
            url=TOKEN_URL, method="POST", **token_success_response()
        )
        token = device_flow.run(
            scopes=["https://www.googleapis.com/auth/youtube.readonly"],
            on_code=lambda code, url, expires: None,
        )
        assert token["access_token"] == "ya29.test-access-token"

    def test_slow_down_backoff_is_additive_5s(
        self, device_flow, httpx_mock: HTTPXMock
    ) -> None:
        httpx_mock.add_response(
            url=DEVICE_AUTH_URL, method="POST", **device_code_response(interval=0)
        )
        httpx_mock.add_response(
            url=TOKEN_URL, method="POST", **token_slow_down_response()
        )
        httpx_mock.add_response(
            url=TOKEN_URL, method="POST", **token_success_response()
        )
        intervals: list[float] = []
        original_run = device_flow.run

        def capturing_run(**kwargs):
            return original_run(**kwargs)

        token = device_flow.run(
            scopes=["https://www.googleapis.com/auth/youtube.readonly"],
            on_code=lambda code, url, expires: None,
            _capture_intervals=intervals,
        )
        assert token["access_token"] == "ya29.test-access-token"
        assert any(i >= 5 for i in intervals), (
            f"expected ≥5s interval after slow_down, got {intervals}"
        )


class TestDeviceFlowExpired:
    def test_expired_token_raises_device_code_timeout(
        self, device_flow, httpx_mock: HTTPXMock
    ) -> None:
        from tube_scout.cli.errors import DeviceCodeTimeout  # noqa: PLC0415

        httpx_mock.add_response(
            url=DEVICE_AUTH_URL, method="POST", **device_code_response()
        )
        httpx_mock.add_response(
            url=TOKEN_URL, method="POST", **token_expired_response()
        )
        with pytest.raises(DeviceCodeTimeout) as exc_info:
            device_flow.run(
                scopes=["https://www.googleapis.com/auth/youtube.readonly"],
                on_code=lambda code, url, expires: None,
            )
        assert "nursing" in exc_info.value.message or exc_info.value.next_command != ""

    def test_expired_token_no_partial_file_on_disk(
        self, device_flow, httpx_mock: HTTPXMock, tmp_path
    ) -> None:
        from tube_scout.cli.errors import DeviceCodeTimeout  # noqa: PLC0415

        httpx_mock.add_response(
            url=DEVICE_AUTH_URL, method="POST", **device_code_response()
        )
        httpx_mock.add_response(
            url=TOKEN_URL, method="POST", **token_expired_response()
        )
        with pytest.raises(DeviceCodeTimeout):
            device_flow.run(
                scopes=["https://www.googleapis.com/auth/youtube.readonly"],
                on_code=lambda code, url, expires: None,
                token_path=tmp_path / "token.json",
            )
        assert not (tmp_path / "token.json").exists()


class TestDeviceFlowAccessDenied:
    def test_access_denied_raises_device_code_access_denied(
        self, device_flow, httpx_mock: HTTPXMock
    ) -> None:
        from tube_scout.cli.errors import DeviceCodeAccessDenied  # noqa: PLC0415

        httpx_mock.add_response(
            url=DEVICE_AUTH_URL, method="POST", **device_code_response()
        )
        httpx_mock.add_response(
            url=TOKEN_URL, method="POST", **token_access_denied_response()
        )
        with pytest.raises(DeviceCodeAccessDenied) as exc_info:
            device_flow.run(
                scopes=["https://www.googleapis.com/auth/youtube.readonly"],
                on_code=lambda code, url, expires: None,
            )
        assert exc_info.value.next_command != ""

    def test_access_denied_no_partial_file_on_disk(
        self, device_flow, httpx_mock: HTTPXMock, tmp_path
    ) -> None:
        from tube_scout.cli.errors import DeviceCodeAccessDenied  # noqa: PLC0415

        httpx_mock.add_response(
            url=DEVICE_AUTH_URL, method="POST", **device_code_response()
        )
        httpx_mock.add_response(
            url=TOKEN_URL, method="POST", **token_access_denied_response()
        )
        with pytest.raises(DeviceCodeAccessDenied):
            device_flow.run(
                scopes=["https://www.googleapis.com/auth/youtube.readonly"],
                on_code=lambda code, url, expires: None,
                token_path=tmp_path / "token.json",
            )
        assert not (tmp_path / "token.json").exists()


class TestDeviceFlowNetworkError:
    def test_network_error_on_device_code_raises_user_facing_error(
        self, device_flow, httpx_mock: HTTPXMock
    ) -> None:
        import httpx as _httpx  # noqa: PLC0415

        from tube_scout.cli.errors import UserFacingError  # noqa: PLC0415

        httpx_mock.add_exception(
            _httpx.ConnectError("Connection refused"), url=DEVICE_AUTH_URL
        )
        with pytest.raises(UserFacingError) as exc_info:
            device_flow.run(
                scopes=["https://www.googleapis.com/auth/youtube.readonly"],
                on_code=lambda code, url, expires: None,
            )
        assert exc_info.value.next_command != ""

    def test_network_error_on_token_poll_raises_user_facing_error(
        self, device_flow, httpx_mock: HTTPXMock
    ) -> None:
        import httpx as _httpx  # noqa: PLC0415

        from tube_scout.cli.errors import UserFacingError  # noqa: PLC0415

        httpx_mock.add_response(
            url=DEVICE_AUTH_URL, method="POST", **device_code_response()
        )
        httpx_mock.add_exception(
            _httpx.ConnectError("Connection refused"), url=TOKEN_URL
        )
        with pytest.raises(UserFacingError) as exc_info:
            device_flow.run(
                scopes=["https://www.googleapis.com/auth/youtube.readonly"],
                on_code=lambda code, url, expires: None,
            )
        assert exc_info.value.next_command != ""


class TestDeviceFlowInvalidClient:
    """HTTP 401 invalid_client from fetch_device_code → ClientTypeNotSupportedForDeviceFlow."""

    def test_fetch_device_code_401_raises_client_type_not_supported(
        self, device_flow, httpx_mock: HTTPXMock
    ) -> None:
        from tube_scout.cli.errors import (
            ClientTypeNotSupportedForDeviceFlow,  # noqa: PLC0415
        )

        httpx_mock.add_response(
            url=DEVICE_AUTH_URL,
            method="POST",
            status_code=401,
            json={
                "error": "invalid_client",
                "error_description": "The OAuth client was not found.",
            },
        )
        with pytest.raises(ClientTypeNotSupportedForDeviceFlow) as exc_info:
            device_flow.fetch_device_code(
                scopes=["https://www.googleapis.com/auth/youtube.readonly"]
            )
        assert exc_info.value.next_command != ""
        assert (
            "TVs and Limited Input" in exc_info.value.message
            or "invalid_client" in exc_info.value.message
        )

    def test_run_401_raises_client_type_not_supported(
        self, device_flow, httpx_mock: HTTPXMock
    ) -> None:
        from tube_scout.cli.errors import (
            ClientTypeNotSupportedForDeviceFlow,  # noqa: PLC0415
        )

        httpx_mock.add_response(
            url=DEVICE_AUTH_URL,
            method="POST",
            status_code=401,
            json={"error": "invalid_client"},
        )
        with pytest.raises(ClientTypeNotSupportedForDeviceFlow):
            device_flow.run(
                scopes=["https://www.googleapis.com/auth/youtube.readonly"],
                on_code=lambda code, url, expires: None,
            )

    def test_register_channel_device_flow_falls_back_to_browser_once(
        self, tmp_path
    ) -> None:
        """When device flow raises ClientTypeNotSupportedForDeviceFlow, fall back to
        browser-redirect exactly once (recursion guard prevents infinite fallback)."""
        from unittest.mock import patch  # noqa: PLC0415

        from tube_scout.cli.errors import (
            ClientTypeNotSupportedForDeviceFlow,  # noqa: PLC0415
        )

        secret_file = tmp_path / "secret.json"
        secret_file.write_text(
            '{"installed": {"client_id": "cid", "client_secret": "csec"}}',
            encoding="utf-8",
        )

        with (
            patch(
                "tube_scout.services.auth._default_client_secret_path",
                return_value=secret_file,
            ),
            patch(
                "tube_scout.services.auth_device_flow.DeviceFlow.run",
                side_effect=ClientTypeNotSupportedForDeviceFlow(alias="nursing"),
            ),
            patch(
                "tube_scout.cli.auth_cli.run_browser_redirect_with_timeout",
            ) as mock_browser,
            patch("tube_scout.services.auth._validate_alias"),
            patch(
                "tube_scout.services.auth._tokens_dir", return_value=tmp_path / "tokens"
            ),
        ):
            from tube_scout.cli.auth_cli import (
                _register_channel_device_flow,  # noqa: PLC0415
            )

            _register_channel_device_flow("nursing")

        assert mock_browser.call_count == 1, (
            f"browser fallback must be called exactly once (recursion guard), got {mock_browser.call_count}"
        )
