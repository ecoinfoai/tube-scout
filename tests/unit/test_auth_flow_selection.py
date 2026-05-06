"""RED unit tests for auth flow selection logic (T009).

Tests the select_auth_flow() function that determines whether to use
device-code flow or browser-redirect flow based on flags and TTY state.

All tests MUST fail (ImportError) until T018 implements
src/tube_scout/cli/auth_cli.py with select_auth_flow().

Contract source: specs/009-runtime-auth-fix/contracts/auth_flow.md
FR-012 (--browser-redirect fallback to device flow in non-TTY)
FR-013-bis (--browser-redirect listener timeout 5 minutes)
"""

from __future__ import annotations

import sys

import pytest


@pytest.fixture
def select_auth_flow():
    """Import select_auth_flow lazily so RED tests fail with ImportError."""
    from tube_scout.cli.auth_cli import select_auth_flow  # noqa: PLC0415

    return select_auth_flow


class TestDeviceFlowDefault:
    def test_no_flag_returns_device_flow(self, select_auth_flow) -> None:
        result = select_auth_flow(browser_redirect=False, is_tty=True)
        assert result == "device"

    def test_no_flag_non_tty_returns_device_flow(self, select_auth_flow) -> None:
        result = select_auth_flow(browser_redirect=False, is_tty=False)
        assert result == "device"


class TestBrowserRedirectWithTTY:
    def test_browser_redirect_with_tty_returns_browser(self, select_auth_flow) -> None:
        result = select_auth_flow(browser_redirect=True, is_tty=True)
        assert result == "browser"

    def test_browser_redirect_with_tty_not_device(self, select_auth_flow) -> None:
        result = select_auth_flow(browser_redirect=True, is_tty=True)
        assert result != "device"


class TestBrowserRedirectFallbackNonTTY:
    def test_browser_redirect_non_tty_falls_back_to_device(
        self, select_auth_flow
    ) -> None:
        """FR-012: --browser-redirect + no TTY → fall back to device-code."""
        result = select_auth_flow(browser_redirect=True, is_tty=False)
        assert result == "device"

    def test_browser_redirect_non_tty_never_binds_port(
        self, select_auth_flow, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Headless contexts MUST NOT bind a TCP listener (auth_flow.md invariant)."""
        import socket  # noqa: PLC0415

        original_bind = socket.socket.bind
        binds: list[tuple] = []

        def capturing_bind(self, address):
            binds.append(address)
            return original_bind(self, address)

        monkeypatch.setattr(socket.socket, "bind", capturing_bind)
        result = select_auth_flow(browser_redirect=True, is_tty=False)
        assert result == "device"
        assert len(binds) == 0, f"Expected no socket.bind calls, got {binds}"


class TestNoStdoutRaisesInteractiveAuthRequired:
    def test_no_tty_no_stdout_raises(
        self, select_auth_flow, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """If even stdout is unavailable, raise InteractiveAuthRequired."""
        from tube_scout.services.auth import InteractiveAuthRequired  # noqa: PLC0415

        monkeypatch.setattr(sys, "stdout", None)
        with pytest.raises(InteractiveAuthRequired):
            select_auth_flow(browser_redirect=False, is_tty=False, has_stdout=False)


class TestBrowserRedirectTimeout:
    def test_browser_redirect_timeout_raises_user_facing_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """FR-013-bis: browser-redirect listener must timeout after 5 minutes."""
        from tube_scout.cli.auth_cli import BrowserRedirectTimeout  # noqa: PLC0415
        from tube_scout.cli.errors import UserFacingError  # noqa: PLC0415

        assert issubclass(BrowserRedirectTimeout, UserFacingError)

    def test_browser_redirect_timeout_has_actionable_next_command(self) -> None:
        from tube_scout.cli.auth_cli import BrowserRedirectTimeout  # noqa: PLC0415

        exc = BrowserRedirectTimeout(alias="nursing")
        assert "auth" in exc.next_command
        assert "nursing" in exc.next_command or "--channel" in exc.next_command

    def test_browser_redirect_timeout_closes_socket(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """FR-013-bis: on timeout, listener socket must be closed (no orphaned port)."""
        from tube_scout.cli.auth_cli import run_browser_redirect_with_timeout  # noqa: PLC0415
        from tube_scout.cli.auth_cli import BrowserRedirectTimeout  # noqa: PLC0415

        import time  # noqa: PLC0415

        monotonic_values = iter([0.0, 301.0])
        monkeypatch.setattr(time, "monotonic", lambda: next(monotonic_values))

        with pytest.raises(BrowserRedirectTimeout):
            run_browser_redirect_with_timeout(alias="nursing", timeout_seconds=300)

    def test_browser_redirect_timeout_no_partial_token(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """FR-013-bis: timeout must not leave partial token file on disk."""
        from tube_scout.cli.auth_cli import run_browser_redirect_with_timeout  # noqa: PLC0415
        from tube_scout.cli.auth_cli import BrowserRedirectTimeout  # noqa: PLC0415

        import time  # noqa: PLC0415

        monotonic_values = iter([0.0, 301.0])
        monkeypatch.setattr(time, "monotonic", lambda: next(monotonic_values))

        token_path = tmp_path / "token.json"
        with pytest.raises(BrowserRedirectTimeout):
            run_browser_redirect_with_timeout(
                alias="nursing", timeout_seconds=300, token_path=token_path
            )
        assert not token_path.exists()
