"""RED integration tests for legacy token migration end-to-end (T011).

Covers every scenario from token_migration.md "Test contract" table:
- match-newer: legacy token newer than alias token → alias token replaced
- match-older: legacy token older than alias token → legacy deleted, alias unchanged
- no-match: legacy channel_id not in registry → legacy deleted
- corrupt: legacy token is corrupt JSON → legacy deleted
- missing: no legacy files → noop
- both-paths-present: both token.json and token_forcessl.json exist

All tests MUST fail (ImportError) until T015 implements
src/tube_scout/services/auth_migration.py.

Contract source: specs/009-runtime-auth-fix/contracts/token_migration.md
FR: FR-008 / FR-009 / FR-010
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import patch

import pytest

VALID_TOKEN_DATA = {
    "token": "ya29.test-access",
    "refresh_token": "1//test-refresh",
    "token_uri": "https://oauth2.googleapis.com/token",
    "client_id": "test-client-id",
    "client_secret": "test-secret",
    "scopes": [
        "https://www.googleapis.com/auth/youtube.force-ssl",
        "https://www.googleapis.com/auth/yt-analytics.readonly",
    ],
}

REGISTRY = {
    "nursing": {
        "alias": "nursing",
        "channel_id": "UCnursing123",
        "display_name": "Nursing Dept",
        "last_used": "2026-05-01T00:00:00+00:00",
    }
}


@pytest.fixture
def config_dir(tmp_path: Path) -> Path:
    d = tmp_path / "tube-scout"
    d.mkdir()
    (d / "tokens").mkdir()
    return d


@pytest.fixture
def run_once(config_dir):
    from tube_scout.services.auth_migration import (
        run_once as _run_once,  # noqa: PLC0415
    )

    return _run_once


class TestMatchNewer:
    def test_newer_legacy_replaces_alias_token(
        self, run_once, config_dir: Path
    ) -> None:
        alias_token = config_dir / "tokens" / "nursing.json"
        alias_token.write_text(json.dumps({"old": True}))
        alias_token.touch()

        time.sleep(0.01)
        legacy = config_dir / "token.json"
        legacy.write_text(json.dumps(VALID_TOKEN_DATA))
        legacy.touch()

        assert legacy.stat().st_mtime > alias_token.stat().st_mtime

        channels_json = config_dir / "tokens" / "channels.json"
        channels_json.write_text(json.dumps(REGISTRY))

        with patch(
            "tube_scout.services.auth_migration.recover_channel_id",
            return_value="UCnursing123",
        ):
            run_once(config_dir=config_dir)

        assert not legacy.exists()
        assert alias_token.exists()
        content = json.loads(alias_token.read_text())
        assert content.get("refresh_token") == "1//test-refresh"

    def test_newer_legacy_removed_after_copy(self, run_once, config_dir: Path) -> None:
        alias_token = config_dir / "tokens" / "nursing.json"
        alias_token.write_text(json.dumps({"old": True}))
        alias_token.touch()

        time.sleep(0.01)
        legacy = config_dir / "token.json"
        legacy.write_text(json.dumps(VALID_TOKEN_DATA))

        channels_json = config_dir / "tokens" / "channels.json"
        channels_json.write_text(json.dumps(REGISTRY))

        with patch(
            "tube_scout.services.auth_migration.recover_channel_id",
            return_value="UCnursing123",
        ):
            run_once(config_dir=config_dir)

        assert not legacy.exists()


class TestMatchOlder:
    def test_older_legacy_is_deleted_alias_unchanged(
        self, run_once, config_dir: Path
    ) -> None:
        legacy = config_dir / "token.json"
        legacy.write_text(json.dumps(VALID_TOKEN_DATA))
        legacy.touch()

        time.sleep(0.01)
        alias_token = config_dir / "tokens" / "nursing.json"
        alias_token.write_text(json.dumps({"newer": True}))
        alias_token.touch()

        assert alias_token.stat().st_mtime > legacy.stat().st_mtime

        channels_json = config_dir / "tokens" / "channels.json"
        channels_json.write_text(json.dumps(REGISTRY))

        original_content = alias_token.read_text()

        with patch(
            "tube_scout.services.auth_migration.recover_channel_id",
            return_value="UCnursing123",
        ):
            run_once(config_dir=config_dir)

        assert not legacy.exists()
        assert alias_token.read_text() == original_content


class TestNoMatch:
    def test_unmatched_channel_id_legacy_deleted(
        self, run_once, config_dir: Path
    ) -> None:
        legacy = config_dir / "token.json"
        legacy.write_text(json.dumps(VALID_TOKEN_DATA))

        channels_json = config_dir / "tokens" / "channels.json"
        channels_json.write_text(json.dumps(REGISTRY))

        with patch(
            "tube_scout.services.auth_migration.recover_channel_id",
            return_value="UCunknown999",
        ):
            run_once(config_dir=config_dir)

        assert not legacy.exists()

    def test_empty_registry_legacy_deleted(self, run_once, config_dir: Path) -> None:
        legacy = config_dir / "token.json"
        legacy.write_text(json.dumps(VALID_TOKEN_DATA))

        channels_json = config_dir / "tokens" / "channels.json"
        channels_json.write_text(json.dumps({}))

        with patch(
            "tube_scout.services.auth_migration.recover_channel_id",
            return_value="UCnursing123",
        ):
            run_once(config_dir=config_dir)

        assert not legacy.exists()


class TestCorrupt:
    def test_corrupt_json_legacy_deleted(self, run_once, config_dir: Path) -> None:
        legacy = config_dir / "token.json"
        legacy.write_text("{corrupted json")
        run_once(config_dir=config_dir)
        assert not legacy.exists()

    def test_corrupt_forcessl_legacy_deleted(self, run_once, config_dir: Path) -> None:
        legacy = config_dir / "token_forcessl.json"
        legacy.write_text("null")
        run_once(config_dir=config_dir)
        assert not legacy.exists()

    def test_corrupt_does_not_affect_tokens_dir(
        self, run_once, config_dir: Path
    ) -> None:
        alias_token = config_dir / "tokens" / "nursing.json"
        alias_token.write_text(json.dumps({"intact": True}))
        (config_dir / "token.json").write_text("{bad}")
        run_once(config_dir=config_dir)
        assert alias_token.exists()
        assert json.loads(alias_token.read_text()) == {"intact": True}


class TestMissing:
    def test_no_legacy_files_is_noop(self, run_once, config_dir: Path) -> None:
        run_once(config_dir=config_dir)
        assert not (config_dir / "token.json").exists()
        assert not (config_dir / "token_forcessl.json").exists()

    def test_missing_returns_without_error(self, run_once, config_dir: Path) -> None:
        run_once(config_dir=config_dir)


class TestBothPathsPresent:
    def test_both_legacy_files_processed(self, run_once, config_dir: Path) -> None:
        (config_dir / "token.json").write_text(json.dumps(VALID_TOKEN_DATA))
        (config_dir / "token_forcessl.json").write_text(json.dumps(VALID_TOKEN_DATA))

        channels_json = config_dir / "tokens" / "channels.json"
        channels_json.write_text(json.dumps(REGISTRY))

        with patch(
            "tube_scout.services.auth_migration.recover_channel_id",
            return_value="UCnursing123",
        ):
            run_once(config_dir=config_dir)

        assert not (config_dir / "token.json").exists()
        assert not (config_dir / "token_forcessl.json").exists()

    def test_cache_file_removed_after_successful_migration(
        self, run_once, config_dir: Path
    ) -> None:
        (config_dir / "token.json").write_text(json.dumps(VALID_TOKEN_DATA))

        channels_json = config_dir / "tokens" / "channels.json"
        channels_json.write_text(json.dumps(REGISTRY))

        cache = config_dir / ".legacy_token_channel_id_cache.json"
        cache.write_text(json.dumps({"cached": True}))

        with patch(
            "tube_scout.services.auth_migration.recover_channel_id",
            return_value="UCnursing123",
        ):
            run_once(config_dir=config_dir)

        assert not cache.exists()

    def test_migrated_token_has_0600_permissions(
        self, run_once, config_dir: Path
    ) -> None:
        alias_token = config_dir / "tokens" / "nursing.json"
        (config_dir / "token.json").write_text(json.dumps(VALID_TOKEN_DATA))

        channels_json = config_dir / "tokens" / "channels.json"
        channels_json.write_text(json.dumps(REGISTRY))

        with patch(
            "tube_scout.services.auth_migration.recover_channel_id",
            return_value="UCnursing123",
        ):
            run_once(config_dir=config_dir)

        if alias_token.exists():
            mode = oct(alias_token.stat().st_mode & 0o777)
            assert mode == "0o600", f"Expected 0600 permissions, got {mode}"
