"""Force-ssl scope detection + headless guard (B7) tests.

Spec: idea6 / FR-IDEA6-005 + NFR-IDEA6-003 / ADR-005 / T-IDEA6-F1+F2.
"""

from __future__ import annotations

from typing import Any

import pytest


class _FakeCreds:
    def __init__(self, scopes: list[str] | None = None) -> None:
        self.scopes = scopes or []


def test_required_scopes_includes_force_ssl() -> None:
    from tube_scout.services.auth import REQUIRED_SCOPES

    assert (
        "https://www.googleapis.com/auth/youtube.force-ssl" in REQUIRED_SCOPES
    )


def test_has_required_scopes_true_when_complete() -> None:
    from tube_scout.services.auth import REQUIRED_SCOPES, has_required_scopes

    creds = _FakeCreds(scopes=list(REQUIRED_SCOPES))
    assert has_required_scopes(creds) is True


def test_has_required_scopes_false_when_missing() -> None:
    from tube_scout.services.auth import has_required_scopes

    creds = _FakeCreds(scopes=["https://www.googleapis.com/auth/yt-analytics.readonly"])
    assert has_required_scopes(creds) is False


def test_verify_scopes_raises_with_alias_and_next_command() -> None:
    from tube_scout.services.auth import (
        ScopeReauthRequired,
        _verify_scopes,
    )

    creds = _FakeCreds(scopes=["https://www.googleapis.com/auth/yt-analytics.readonly"])
    with pytest.raises(ScopeReauthRequired) as exc_info:
        _verify_scopes(creds, alias="nursing")
    err = exc_info.value
    assert err.alias == "nursing"
    assert any("force-ssl" in s for s in err.missing)
    assert "tube-scout auth --revoke nursing" in err.next_command
    assert "tube-scout auth --channel nursing" in err.next_command


def test_headless_guard_blocks_authenticate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """B7: ``authenticate`` raises InteractiveAuthRequired in non-TTY ctx."""
    import sys

    from tube_scout.services.auth import (
        InteractiveAuthRequired,
        authenticate,
    )

    # Force isatty False to simulate systemd context.
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    # Token absent so the flow falls through to flow.run_local_server.
    monkeypatch.setattr(
        "tube_scout.services.auth._token_path",
        lambda: __import__("pathlib").Path("/nonexistent/never.json"),
    )
    with pytest.raises(InteractiveAuthRequired) as exc_info:
        authenticate()
    assert "TTY" in exc_info.value.message
    assert "ssh to host" in exc_info.value.next_command


def test_headless_guard_blocks_register_channel(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """B7: ``register_channel`` also raises before flow.run_local_server."""
    import sys

    from tube_scout.services.auth import (
        InteractiveAuthRequired,
        register_channel,
    )

    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    # Make the alias unique so register_channel does not short-circuit
    # on an existing token (uses _tokens_dir which we override).
    monkeypatch.setenv("TUBE_SCOUT_TOKENS_DIR", str(tmp_path / "tokens"))
    with pytest.raises(InteractiveAuthRequired) as exc_info:
        register_channel(alias="nursing")
    assert exc_info.value.alias == "nursing"
