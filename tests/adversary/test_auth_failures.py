"""Adversary tests for multi-channel authentication edge cases."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from google.auth.exceptions import RefreshError

from tube_scout.services.auth import (
    authenticate_channel,
    load_registry,
    revoke_channel,
)


@pytest.fixture()
def tokens_dir(tmp_path: Path) -> Path:
    """Create a temporary tokens directory."""
    d = tmp_path / "tokens"
    d.mkdir()
    return d


@pytest.fixture()
def _mock_tokens_dir(tokens_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Set TUBE_SCOUT_TOKENS_DIR to temporary directory."""
    monkeypatch.setenv("TUBE_SCOUT_TOKENS_DIR", str(tokens_dir))


@pytest.fixture()
def sample_registry_with_token(tokens_dir: Path) -> Path:
    """Create a sample registry and token file."""
    registry = {
        "간호학과": {
            "alias": "간호학과",
            "channel_id": "UCxxxxxxxxxxxxxxxxxxxxxx",
            "channel_name": "부산보건대 간호학과",
            "registered_at": "2026-04-04T12:00:00",
            "last_used_at": "2026-04-04T15:30:00",
            "token_path": str(tokens_dir / "간호학과.json"),
        },
    }
    channels_file = tokens_dir / "channels.json"
    channels_file.write_text(json.dumps(registry, ensure_ascii=False), encoding="utf-8")

    token_data = {
        "token": "ya29.expired_token",
        "refresh_token": "1//revoked_refresh",
        "token_uri": "https://oauth2.googleapis.com/token",
        "client_id": "fake_client_id",
        "client_secret": "fake_client_secret",
        "scopes": [
            "https://www.googleapis.com/auth/youtube.readonly",
        ],
    }
    token_file = tokens_dir / "간호학과.json"
    token_file.write_text(json.dumps(token_data), encoding="utf-8")
    return channels_file


class TestExpiredTokenRefreshFailure:
    """Tests for expired tokens that cannot be refreshed."""

    @pytest.mark.usefixtures("_mock_tokens_dir")
    def test_refresh_error_raises(
        self, sample_registry_with_token: Path
    ) -> None:
        mock_creds = MagicMock()
        mock_creds.valid = False
        mock_creds.expired = True
        mock_creds.refresh_token = "1//revoked_refresh"
        mock_creds.refresh.side_effect = RefreshError("Token has been revoked")

        with patch(
            "tube_scout.services.auth.Credentials.from_authorized_user_file",
            return_value=mock_creds,
        ), patch("tube_scout.services.auth.Request"):
            with pytest.raises(RefreshError):
                authenticate_channel("간호학과")


class TestRevokedCredentials:
    """Tests for revoked or deleted credentials."""

    @pytest.mark.usefixtures("_mock_tokens_dir")
    def test_missing_token_file_raises(
        self, tokens_dir: Path, sample_registry_with_token: Path
    ) -> None:
        # Delete the token file but keep registry entry
        token_file = tokens_dir / "간호학과.json"
        token_file.unlink()

        with pytest.raises(FileNotFoundError, match="Token file"):
            authenticate_channel("간호학과")


class TestMissingAlias:
    """Tests for operations on non-existent aliases."""

    @pytest.mark.usefixtures("_mock_tokens_dir")
    def test_authenticate_missing_alias(self) -> None:
        with pytest.raises(KeyError, match="not registered"):
            authenticate_channel("존재하지않는학과")

    @pytest.mark.usefixtures("_mock_tokens_dir")
    def test_revoke_missing_alias(self) -> None:
        with pytest.raises(KeyError, match="not registered"):
            revoke_channel("존재하지않는학과")


class TestCorruptRegistry:
    """Tests for corrupt channels.json."""

    @pytest.mark.usefixtures("_mock_tokens_dir")
    def test_corrupt_json_raises(self, tokens_dir: Path) -> None:
        channels_file = tokens_dir / "channels.json"
        channels_file.write_text("{invalid json content", encoding="utf-8")

        with pytest.raises(json.JSONDecodeError):
            load_registry(tokens_dir)

    @pytest.mark.usefixtures("_mock_tokens_dir")
    def test_empty_file_returns_empty(self, tokens_dir: Path) -> None:
        channels_file = tokens_dir / "channels.json"
        channels_file.write_text("", encoding="utf-8")

        # Empty file should raise or return empty
        with pytest.raises(json.JSONDecodeError):
            load_registry(tokens_dir)


class TestTokenNoRefreshToken:
    """Tests for tokens without refresh_token."""

    @pytest.mark.usefixtures("_mock_tokens_dir")
    def test_expired_no_refresh_token_raises(
        self, sample_registry_with_token: Path
    ) -> None:
        mock_creds = MagicMock()
        mock_creds.valid = False
        mock_creds.expired = True
        mock_creds.refresh_token = None

        with patch(
            "tube_scout.services.auth.Credentials.from_authorized_user_file",
            return_value=mock_creds,
        ):
            with pytest.raises(
                ValueError, match="cannot be refreshed"
            ):
                authenticate_channel("간호학과")
