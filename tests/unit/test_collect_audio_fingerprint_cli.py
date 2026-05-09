"""T030 RED — collect audio + collect fingerprint CLI 5 scenarios."""
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from tube_scout.cli.main import app

runner = CliRunner()


def _mock_mgr(tmp_path: Path) -> MagicMock:
    """Build a fake project manager pointing at tmp_path."""
    mgr = MagicMock()
    mgr.project_dir = str(tmp_path)
    return mgr


def test_collect_audio_channel_dispatches(tmp_path) -> None:
    """Scenario 1: collect audio --channel <alias> dispatches to audio pipeline."""
    captured: dict = {}

    # Create dummy videos_meta.json so the command finds video_ids
    channel_dir = tmp_path / "01_collect" / "channels" / "UC_TEST_001"
    channel_dir.mkdir(parents=True)
    (channel_dir / "videos_meta.json").write_text(
        '[{"video_id": "aaaaaaaaaaa"}]', encoding="utf-8"
    )

    def fake_dispatch(**kwargs):
        captured.update(kwargs)

    with patch(
        "tube_scout.cli.collect.dispatch_audio_fingerprint",
        side_effect=fake_dispatch,
    ), patch(
        "tube_scout.cli.collect.resolve_alias_to_channel_id",
        return_value="UC_TEST_001",
    ), patch(
        "tube_scout.cli.collect.resolve_project",
        return_value=_mock_mgr(tmp_path),
    ), patch(
        "tube_scout.storage.content_db.migrate_to_v3",
    ):
        result = runner.invoke(
            app,
            ["collect", "audio", "--channel", "nursing"],
        )

    assert captured.get("channel") == "nursing"


def test_collect_fingerprint_alias_equals_collect_audio(tmp_path) -> None:
    """Scenario 2: collect fingerprint --channel X behaves same as collect audio --channel X."""
    audio_captured: dict = {}
    fingerprint_captured: dict = {}

    channel_dir = tmp_path / "01_collect" / "channels" / "UC_TEST_002"
    channel_dir.mkdir(parents=True)
    (channel_dir / "videos_meta.json").write_text(
        '[{"video_id": "bbbbbbbbbbb"}]', encoding="utf-8"
    )

    def fake_audio_dispatch(**kwargs):
        audio_captured.update(kwargs)

    def fake_fingerprint_dispatch(**kwargs):
        fingerprint_captured.update(kwargs)

    with patch(
        "tube_scout.cli.collect.dispatch_audio_fingerprint",
        side_effect=fake_audio_dispatch,
    ), patch(
        "tube_scout.cli.collect.resolve_alias_to_channel_id",
        return_value="UC_TEST_002",
    ), patch(
        "tube_scout.cli.collect.resolve_project",
        return_value=_mock_mgr(tmp_path),
    ), patch(
        "tube_scout.storage.content_db.migrate_to_v3",
    ):
        runner.invoke(app, ["collect", "audio", "--channel", "nursing"])

    with patch(
        "tube_scout.cli.collect.dispatch_audio_fingerprint",
        side_effect=fake_fingerprint_dispatch,
    ), patch(
        "tube_scout.cli.collect.resolve_alias_to_channel_id",
        return_value="UC_TEST_002",
    ), patch(
        "tube_scout.cli.collect.resolve_project",
        return_value=_mock_mgr(tmp_path),
    ), patch(
        "tube_scout.storage.content_db.migrate_to_v3",
    ):
        runner.invoke(app, ["collect", "fingerprint", "--channel", "nursing"])

    assert audio_captured.get("channel") == fingerprint_captured.get("channel")


def test_collect_audio_all_channels(tmp_path) -> None:
    """Scenario 3: collect audio --all-channels dispatches per-channel with video_ids (G-2)."""
    import json

    channel_dir = tmp_path / "01_collect" / "channels" / "UC_CH1_TEST001"
    channel_dir.mkdir(parents=True)
    (channel_dir / "videos_meta.json").write_text(
        json.dumps([{"video_id": "AAAAAAAAAAA"}]), encoding="utf-8"
    )

    dispatch_calls: list[dict] = []

    def fake_dispatch(**kwargs):
        dispatch_calls.append(dict(kwargs))

    with patch(
        "tube_scout.cli.collect.dispatch_audio_fingerprint",
        side_effect=fake_dispatch,
    ), patch(
        "tube_scout.cli.collect.resolve_project",
        return_value=_mock_mgr(tmp_path),
    ), patch(
        "tube_scout.cli.collect.resolve_alias_to_channel_id",
        return_value="UC_CH1_TEST001",
    ), patch(
        "tube_scout.storage.content_db.migrate_to_v3",
    ), patch(
        "tube_scout.services.auth.load_registry",
        return_value={"ch1": MagicMock()},
    ):
        result = runner.invoke(
            app,
            ["collect", "audio", "--all-channels"],
        )

    # G-2: per-channel dispatch with non-None video_ids
    assert len(dispatch_calls) >= 1, "dispatch must be called at least once"
    assert dispatch_calls[0].get("video_ids") is not None, "video_ids must not be None"


def test_collect_audio_force_flag(tmp_path) -> None:
    """Scenario 4: collect audio --force sets force=True in dispatch."""
    captured: dict = {}

    channel_dir = tmp_path / "01_collect" / "channels" / "UC_TEST_004"
    channel_dir.mkdir(parents=True)
    (channel_dir / "videos_meta.json").write_text(
        '[{"video_id": "ccccccccccc"}]', encoding="utf-8"
    )

    def fake_dispatch(**kwargs):
        captured.update(kwargs)

    with patch(
        "tube_scout.cli.collect.dispatch_audio_fingerprint",
        side_effect=fake_dispatch,
    ), patch(
        "tube_scout.cli.collect.resolve_alias_to_channel_id",
        return_value="UC_TEST_004",
    ), patch(
        "tube_scout.cli.collect.resolve_project",
        return_value=_mock_mgr(tmp_path),
    ), patch(
        "tube_scout.storage.content_db.migrate_to_v3",
    ):
        result = runner.invoke(
            app,
            ["collect", "audio", "--channel", "nursing", "--force"],
        )

    assert captured.get("force") is True


def test_collect_audio_channel_and_all_channels_mutual_exclusion() -> None:
    """Scenario 5: collect audio --channel X --all-channels → exit 2."""
    result = runner.invoke(
        app,
        ["collect", "audio", "--channel", "nursing", "--all-channels"],
    )
    assert result.exit_code == 2
