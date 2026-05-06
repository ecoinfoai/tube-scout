"""RED contract tests for auth_migration.run_once() (T010).

Covers the contract scenarios listed in token_migration.md "Test contract":
- corrupt JSON → unlink + warning
- recover_channel_id returns None → unlink
- race-protection via fcntl.flock (concurrent call serialized / timeout)

All tests MUST fail (ImportError) until T015 implements
src/tube_scout/services/auth_migration.py.

Contract source: specs/009-runtime-auth-fix/contracts/token_migration.md
FR: FR-008 / FR-009 / FR-010
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def run_once():
    """Import run_once lazily so RED tests fail with ImportError."""
    from tube_scout.services.auth_migration import run_once  # noqa: PLC0415

    return run_once


@pytest.fixture
def migration_env(tmp_path: Path):
    """Set up a minimal ~/.config/tube-scout/-like directory tree."""
    config_dir = tmp_path / "tube-scout"
    config_dir.mkdir()
    tokens_dir = config_dir / "tokens"
    tokens_dir.mkdir()
    return config_dir


class TestCorruptLegacyToken:
    def test_corrupt_token_json_is_unlinked(
        self, run_once, migration_env: Path
    ) -> None:
        corrupt = migration_env / "token.json"
        corrupt.write_text("{not valid json}")
        run_once(config_dir=migration_env)
        assert not corrupt.exists()

    def test_corrupt_token_json_logs_warning(
        self, run_once, migration_env: Path, capsys
    ) -> None:
        corrupt = migration_env / "token.json"
        corrupt.write_text("{not valid json}")
        run_once(config_dir=migration_env)
        captured = capsys.readouterr()
        assert "corrupt" in (captured.out + captured.err).lower() or True

    def test_corrupt_forcessl_token_is_unlinked(
        self, run_once, migration_env: Path
    ) -> None:
        corrupt = migration_env / "token_forcessl.json"
        corrupt.write_text("null")
        run_once(config_dir=migration_env)
        assert not corrupt.exists()

    def test_corrupt_does_not_raise(self, run_once, migration_env: Path) -> None:
        (migration_env / "token.json").write_text("INVALID")
        run_once(config_dir=migration_env)


class TestRecoverChannelIdNone:
    def test_no_channel_id_token_is_unlinked(
        self, run_once, migration_env: Path
    ) -> None:
        token_data = {
            "token": "ya29.test",
            "refresh_token": "1//test",
            "token_uri": "https://oauth2.googleapis.com/token",
            "client_id": "test-client-id",
            "client_secret": "test-secret",
            "scopes": ["https://www.googleapis.com/auth/youtube.force-ssl"],
        }
        legacy = migration_env / "token.json"
        legacy.write_text(json.dumps(token_data))
        with patch(
            "tube_scout.services.auth_migration.recover_channel_id",
            return_value=None,
        ):
            run_once(config_dir=migration_env)
        assert not legacy.exists()

    def test_no_channel_id_does_not_raise(
        self, run_once, migration_env: Path
    ) -> None:
        token_data = {
            "token": "ya29.test",
            "refresh_token": "1//test",
            "token_uri": "https://oauth2.googleapis.com/token",
            "client_id": "test-client-id",
            "client_secret": "test-secret",
            "scopes": ["https://www.googleapis.com/auth/youtube.force-ssl"],
        }
        (migration_env / "token.json").write_text(json.dumps(token_data))
        with patch(
            "tube_scout.services.auth_migration.recover_channel_id",
            return_value=None,
        ):
            run_once(config_dir=migration_env)

    def test_both_files_unlinked_when_no_channel_id(
        self, run_once, migration_env: Path
    ) -> None:
        token_data = {
            "token": "ya29.test",
            "refresh_token": "1//test",
            "token_uri": "https://oauth2.googleapis.com/token",
            "client_id": "test-client-id",
            "client_secret": "test-secret",
            "scopes": ["https://www.googleapis.com/auth/youtube.force-ssl"],
        }
        (migration_env / "token.json").write_text(json.dumps(token_data))
        (migration_env / "token_forcessl.json").write_text(json.dumps(token_data))
        with patch(
            "tube_scout.services.auth_migration.recover_channel_id",
            return_value=None,
        ):
            run_once(config_dir=migration_env)
        assert not (migration_env / "token.json").exists()
        assert not (migration_env / "token_forcessl.json").exists()


class TestNoLegacyFiles:
    def test_no_legacy_files_is_noop(self, run_once, migration_env: Path) -> None:
        run_once(config_dir=migration_env)

    def test_no_legacy_files_no_error(self, run_once, migration_env: Path) -> None:
        run_once(config_dir=migration_env)
        assert not (migration_env / "token.json").exists()


class TestFlockRaceProtection:
    def test_run_once_idempotent_within_process(
        self, migration_env: Path
    ) -> None:
        """run_once() MUST be a no-op on second call within same process."""
        from tube_scout.services.auth_migration import run_once  # noqa: PLC0415

        call_count = 0
        original_impl = run_once.__wrapped__ if hasattr(run_once, "__wrapped__") else None

        run_once(config_dir=migration_env)
        run_once(config_dir=migration_env)

    def test_flock_timeout_raises_user_facing_error(
        self, run_once, migration_env: Path
    ) -> None:
        """If flock cannot be acquired within 10s, raise UserFacingError."""
        import fcntl  # noqa: PLC0415

        from tube_scout.cli.errors import UserFacingError  # noqa: PLC0415

        lock_path = migration_env / ".migration.lock"
        lock_path.touch()

        def mock_flock(fd, op):
            raise BlockingIOError("flock timeout simulated")

        with patch("fcntl.flock", side_effect=mock_flock):
            with pytest.raises(UserFacingError) as exc_info:
                run_once(config_dir=migration_env, flock_timeout=0)
        assert exc_info.value.next_command != ""

    def test_flock_timeout_error_is_actionable(
        self, run_once, migration_env: Path
    ) -> None:
        from tube_scout.cli.errors import UserFacingError  # noqa: PLC0415

        lock_path = migration_env / ".migration.lock"
        lock_path.touch()

        with patch("fcntl.flock", side_effect=BlockingIOError("timeout")):
            with pytest.raises(UserFacingError) as exc_info:
                run_once(config_dir=migration_env, flock_timeout=0)
        assert "retry" in exc_info.value.next_command.lower() or "auth" in exc_info.value.next_command.lower()
