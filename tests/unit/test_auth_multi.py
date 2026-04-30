"""Tests for multi-channel authentication."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tube_scout.services.auth import (
    authenticate_channel,
    list_channels,
    load_registry,
    register_channel,
    revoke_channel,
    save_registry,
    update_last_used,
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
def sample_registry(tokens_dir: Path) -> Path:
    """Create a sample channels.json registry."""
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
    return channels_file


@pytest.fixture()
def sample_token(tokens_dir: Path) -> Path:
    """Create a sample token file for 간호학과."""
    token_data = {
        "token": "ya29.fake_access_token",
        "refresh_token": "1//fake_refresh_token",
        "token_uri": "https://oauth2.googleapis.com/token",
        "client_id": "fake_client_id",
        "client_secret": "fake_client_secret",
        "scopes": [
            "https://www.googleapis.com/auth/youtube.readonly",
            "https://www.googleapis.com/auth/yt-analytics.readonly",
        ],
    }
    token_file = tokens_dir / "간호학과.json"
    token_file.write_text(json.dumps(token_data), encoding="utf-8")
    return token_file


class TestLoadRegistry:
    """Tests for load_registry function."""

    def test_load_existing_registry(
        self, tokens_dir: Path, sample_registry: Path
    ) -> None:
        registry = load_registry(tokens_dir)
        assert "간호학과" in registry
        assert registry["간호학과"].channel_id == "UCxxxxxxxxxxxxxxxxxxxxxx"

    def test_load_empty_dir_returns_empty_dict(self, tokens_dir: Path) -> None:
        registry = load_registry(tokens_dir)
        assert registry == {}

    def test_load_creates_dir_if_missing(self, tmp_path: Path) -> None:
        missing_dir = tmp_path / "nonexistent" / "tokens"
        registry = load_registry(missing_dir)
        assert registry == {}
        assert missing_dir.exists()


class TestSaveRegistry:
    """Tests for save_registry function."""

    def test_save_and_reload(self, tokens_dir: Path) -> None:
        from tube_scout.models.config import ChannelRegistration

        reg = ChannelRegistration(
            alias="물리치료과",
            channel_id="UCtest1234567890abcdef",
            channel_name="부산보건대 물리치료과",
            registered_at="2026-04-04T12:00:00",
            last_used_at="2026-04-04T12:00:00",
            token_path=str(tokens_dir / "물리치료과.json"),
        )
        save_registry(tokens_dir, {"물리치료과": reg})
        reloaded = load_registry(tokens_dir)
        assert "물리치료과" in reloaded
        assert reloaded["물리치료과"].channel_id == "UCtest1234567890abcdef"


class TestUpdateLastUsed:
    """Tests for update_last_used function."""

    def test_update_last_used_timestamp(
        self, tokens_dir: Path, sample_registry: Path
    ) -> None:
        registry = load_registry(tokens_dir)
        old_timestamp = registry["간호학과"].last_used_at
        update_last_used(tokens_dir, "간호학과")
        updated = load_registry(tokens_dir)
        assert updated["간호학과"].last_used_at != old_timestamp

    def test_update_missing_alias_raises(self, tokens_dir: Path) -> None:
        with pytest.raises(KeyError, match="not registered"):
            update_last_used(tokens_dir, "nonexistent")


class TestListChannels:
    """Tests for list_channels function."""

    @pytest.mark.usefixtures("_mock_tokens_dir")
    def test_list_with_registered_channels(self, sample_registry: Path) -> None:
        channels = list_channels()
        assert len(channels) == 1
        assert channels[0].alias == "간호학과"

    @pytest.mark.usefixtures("_mock_tokens_dir")
    def test_list_empty(self) -> None:
        channels = list_channels()
        assert channels == []


class TestRevokeChannel:
    """Tests for revoke_channel function."""

    @pytest.mark.usefixtures("_mock_tokens_dir")
    def test_revoke_removes_token_and_registry(
        self, tokens_dir: Path, sample_registry: Path, sample_token: Path
    ) -> None:
        assert sample_token.exists()
        revoke_channel("간호학과")
        assert not sample_token.exists()
        registry = load_registry(tokens_dir)
        assert "간호학과" not in registry

    @pytest.mark.usefixtures("_mock_tokens_dir")
    def test_revoke_missing_alias_raises(self) -> None:
        with pytest.raises(KeyError, match="not registered"):
            revoke_channel("nonexistent")


class TestAuthenticateChannel:
    """Tests for authenticate_channel function."""

    @pytest.mark.usefixtures("_mock_tokens_dir")
    def test_authenticate_with_valid_token(
        self, tokens_dir: Path, sample_registry: Path, sample_token: Path
    ) -> None:
        from tube_scout.services.auth import SCOPES

        mock_creds = MagicMock()
        mock_creds.valid = True
        # idea6 ADR-IDEA6-005 / FR-IDEA6-005: _verify_scopes runs after
        # every creds.valid path. Stub the scope set to satisfy the check.
        mock_creds.scopes = list(SCOPES)
        mock_creds.granted_scopes = list(SCOPES)
        with patch(
            "tube_scout.services.auth.Credentials.from_authorized_user_file",
            return_value=mock_creds,
        ):
            creds = authenticate_channel("간호학과")
            assert creds is mock_creds

    @pytest.mark.usefixtures("_mock_tokens_dir")
    def test_authenticate_refreshes_expired_token(
        self, tokens_dir: Path, sample_registry: Path, sample_token: Path
    ) -> None:
        from tube_scout.services.auth import SCOPES

        mock_creds = MagicMock()
        mock_creds.valid = False
        mock_creds.expired = True
        mock_creds.refresh_token = "1//fake_refresh_token"
        mock_creds.to_json.return_value = '{"token": "refreshed"}'
        mock_creds.scopes = list(SCOPES)
        mock_creds.granted_scopes = list(SCOPES)

        with (
            patch(
                "tube_scout.services.auth.Credentials.from_authorized_user_file",
                return_value=mock_creds,
            ),
            patch("tube_scout.services.auth.Request"),
        ):
            creds = authenticate_channel("간호학과")
            mock_creds.refresh.assert_called_once()
            assert creds is mock_creds

    @pytest.mark.usefixtures("_mock_tokens_dir")
    def test_authenticate_missing_alias_raises(self) -> None:
        with pytest.raises(KeyError, match="not registered"):
            authenticate_channel("nonexistent")


class TestRegisterChannel:
    """Tests for register_channel function."""

    @pytest.fixture(autouse=True)
    def _force_tty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """idea6 NFR-IDEA6-003 §"Headless guard": pretend a TTY is attached.

        register_channel now refuses ``flow.run_local_server`` in non-TTY
        contexts (B7). The unit tests mock the flow itself so we just
        force ``sys.stdin.isatty`` -> True for the duration of each test.
        """
        import sys

        monkeypatch.setattr(sys.stdin, "isatty", lambda: True)

    @pytest.mark.usefixtures("_mock_tokens_dir")
    def test_register_saves_token_and_registry(self, tokens_dir: Path) -> None:
        from tube_scout.services.auth import SCOPES

        mock_creds = MagicMock()
        mock_creds.to_json.return_value = '{"token": "fake"}'
        mock_creds.scopes = list(SCOPES)
        mock_creds.granted_scopes = list(SCOPES)

        mock_flow = MagicMock()
        mock_flow.run_local_server.return_value = mock_creds

        mock_channels_response = {
            "items": [
                {
                    "id": "UCnew_channel_id_12345",
                    "snippet": {"title": "새학과 채널"},
                }
            ]
        }

        with (
            patch(
                "tube_scout.services.auth.InstalledAppFlow.from_client_secrets_file",
                return_value=mock_flow,
            ),
            patch(
                "tube_scout.services.auth._default_client_secret_path",
                return_value=Path("/fake/client_secret.json"),
            ),
            patch(
                "tube_scout.services.auth.build",
            ) as mock_build,
        ):
            mock_service = MagicMock()
            mock_build.return_value = mock_service
            ch_list = mock_service.channels.return_value.list
            ch_list.return_value.execute.return_value = mock_channels_response

            reg = register_channel("새학과")

        assert reg.alias == "새학과"
        assert reg.channel_id == "UCnew_channel_id_12345"
        assert reg.channel_name == "새학과 채널"
        assert (tokens_dir / "새학과.json").exists()

        registry = load_registry(tokens_dir)
        assert "새학과" in registry

    @pytest.mark.usefixtures("_mock_tokens_dir")
    def test_register_no_channel_found_raises(self, tokens_dir: Path) -> None:
        from tube_scout.services.auth import SCOPES

        mock_creds = MagicMock()
        mock_creds.scopes = list(SCOPES)
        mock_creds.granted_scopes = list(SCOPES)
        mock_flow = MagicMock()
        mock_flow.run_local_server.return_value = mock_creds

        with (
            patch(
                "tube_scout.services.auth.InstalledAppFlow.from_client_secrets_file",
                return_value=mock_flow,
            ),
            patch(
                "tube_scout.services.auth._default_client_secret_path",
                return_value=Path("/fake/client_secret.json"),
            ),
            patch(
                "tube_scout.services.auth.build",
            ) as mock_build,
        ):
            mock_service = MagicMock()
            mock_build.return_value = mock_service
            ch_list = mock_service.channels.return_value.list
            ch_list.return_value.execute.return_value = {"items": []}

            with pytest.raises(ValueError, match="No channel found"):
                register_channel("빈학과")

    @pytest.mark.usefixtures("_mock_tokens_dir")
    def test_register_auto_detects_channel_id(self, tokens_dir: Path) -> None:
        from tube_scout.services.auth import SCOPES

        mock_creds = MagicMock()
        mock_creds.to_json.return_value = '{"token": "fake"}'
        mock_creds.scopes = list(SCOPES)
        mock_creds.granted_scopes = list(SCOPES)

        mock_flow = MagicMock()
        mock_flow.run_local_server.return_value = mock_creds

        mock_channels_response = {
            "items": [
                {
                    "id": "UCauto_detected_chan_123",
                    "snippet": {"title": "자동감지 채널"},
                }
            ]
        }

        with (
            patch(
                "tube_scout.services.auth.InstalledAppFlow.from_client_secrets_file",
                return_value=mock_flow,
            ),
            patch(
                "tube_scout.services.auth._default_client_secret_path",
                return_value=Path("/fake/client_secret.json"),
            ),
            patch(
                "tube_scout.services.auth.build",
            ) as mock_build,
        ):
            mock_service = MagicMock()
            mock_build.return_value = mock_service
            ch_list = mock_service.channels.return_value.list
            ch_list.return_value.execute.return_value = mock_channels_response

            reg = register_channel("자동학과")
            assert reg.channel_id == "UCauto_detected_chan_123"


class TestSecureWrite:
    """Tests for _secure_write helper (H-02+L-07)."""

    def test_secure_write_sets_permissions_0600(self, tmp_path: Path) -> None:
        """Written files should have 0o600 permissions."""
        from tube_scout.services.auth import _secure_write

        target = tmp_path / "secret.json"
        _secure_write(target, '{"token": "abc"}')
        assert target.exists()
        assert oct(target.stat().st_mode & 0o777) == oct(0o600)

    def test_secure_write_is_atomic(self, tmp_path: Path) -> None:
        """If write fails, original file should remain intact."""
        from tube_scout.services.auth import _secure_write

        target = tmp_path / "secret.json"
        _secure_write(target, '{"old": true}')
        target.read_text()

        # Overwrite with new content
        _secure_write(target, '{"new": true}')
        assert target.read_text() == '{"new": true}'
        assert oct(target.stat().st_mode & 0o777) == oct(0o600)

    def test_save_registry_sets_permissions(self, tokens_dir: Path) -> None:
        """save_registry should produce a 0o600 channels.json."""
        from tube_scout.models.config import ChannelRegistration

        reg = ChannelRegistration(
            alias="test",
            channel_id="UCtest",
            channel_name="Test",
            registered_at="2026-04-04T12:00:00",
            last_used_at="2026-04-04T12:00:00",
            token_path=str(tokens_dir / "test.json"),
        )
        save_registry(tokens_dir, {"test": reg})
        channels_file = tokens_dir / "channels.json"
        assert oct(channels_file.stat().st_mode & 0o777) == oct(0o600)
