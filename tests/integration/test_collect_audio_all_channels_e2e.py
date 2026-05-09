"""T059 RED — G-2: --all-channels video_ids extraction and dispatch.

Verifies that collect audio/fingerprint --all-channels correctly:
  - iterates all registered channels
  - loads videos_meta.json for each
  - dispatches with actual video_ids (not None)
"""
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from tube_scout.cli.main import app

runner = CliRunner()


def _mock_mgr(project_dir: Path) -> MagicMock:
    mgr = MagicMock()
    mgr.project_dir = str(project_dir)
    return mgr


def _setup_channels(project_dir: Path, channels: dict[str, list[str]]) -> None:
    """Create videos_meta.json for each channel_id → [video_id, ...] mapping."""
    for channel_id, video_ids in channels.items():
        channel_dir = project_dir / "01_collect" / "channels" / channel_id
        channel_dir.mkdir(parents=True, exist_ok=True)
        (channel_dir / "videos_meta.json").write_text(
            json.dumps([{"video_id": vid} for vid in video_ids]),
            encoding="utf-8",
        )


def test_all_channels_dispatches_with_video_ids(tmp_path: Path) -> None:
    """G-2: --all-channels must dispatch with non-None video_ids for each channel."""
    channels = {
        "UC_G2_CH001A": ["AAAAAAAAA01", "AAAAAAAAA02"],
        "UC_G2_CH002A": ["BBBBBBBBB01"],
    }
    _setup_channels(tmp_path, channels)

    registry = {
        "ch1": MagicMock(channel_id="UC_G2_CH001A"),
        "ch2": MagicMock(channel_id="UC_G2_CH002A"),
    }

    dispatch_calls: list[dict] = []

    def fake_dispatch(**kwargs):
        dispatch_calls.append(kwargs)

    def fake_resolve_alias(alias: str) -> str:
        return {"ch1": "UC_G2_CH001A", "ch2": "UC_G2_CH002A"}[alias]

    with patch("tube_scout.cli.collect.resolve_project", return_value=_mock_mgr(tmp_path)), \
         patch("tube_scout.cli.collect.resolve_alias_to_channel_id", side_effect=fake_resolve_alias), \
         patch("tube_scout.cli.collect.dispatch_audio_fingerprint", side_effect=fake_dispatch), \
         patch("tube_scout.services.auth.load_registry", return_value=registry), \
         patch("tube_scout.storage.content_db.migrate_to_v3"):
        result = runner.invoke(app, ["collect", "audio", "--all-channels"])

    assert result.exit_code in (0, 1), f"Unexpected exit: {result.exit_code}\n{result.output}"
    assert len(dispatch_calls) >= 1, "dispatch must be called at least once"

    # ALL dispatch calls must have non-None video_ids
    for call in dispatch_calls:
        assert call.get("video_ids") is not None, (
            f"dispatch called with video_ids=None: {call}"
        )

    # Collect all dispatched video_ids
    all_dispatched = []
    for call in dispatch_calls:
        all_dispatched.extend(call.get("video_ids") or [])

    expected_all = ["AAAAAAAAA01", "AAAAAAAAA02", "BBBBBBBBB01"]
    for vid in expected_all:
        assert vid in all_dispatched, f"video_id {vid!r} not dispatched; got {all_dispatched}"


def test_all_channels_silent_return_regression(tmp_path: Path) -> None:
    """G-2: video_ids=None dispatch must NOT silently return with 0 processing."""
    channels = {"UC_G2_CH003A": ["CCCCCCCCC01"]}
    _setup_channels(tmp_path, channels)

    registry = {"ch3": MagicMock(channel_id="UC_G2_CH003A")}

    video_ids_seen: list = []
    original_dispatch = __import__(
        "tube_scout.cli.collect", fromlist=["dispatch_audio_fingerprint"]
    ).dispatch_audio_fingerprint

    def spy_dispatch(**kwargs):
        video_ids_seen.append(kwargs.get("video_ids"))

    with patch("tube_scout.cli.collect.resolve_project", return_value=_mock_mgr(tmp_path)), \
         patch("tube_scout.cli.collect.resolve_alias_to_channel_id",
               return_value="UC_G2_CH003A"), \
         patch("tube_scout.cli.collect.dispatch_audio_fingerprint", side_effect=spy_dispatch), \
         patch("tube_scout.services.auth.load_registry", return_value=registry), \
         patch("tube_scout.storage.content_db.migrate_to_v3"):
        runner.invoke(app, ["collect", "audio", "--all-channels"])

    assert video_ids_seen, "dispatch must be called"
    assert all(v is not None for v in video_ids_seen), (
        f"dispatch was called with video_ids=None: {video_ids_seen}"
    )


def test_all_channels_per_channel_isolation(tmp_path: Path) -> None:
    """G-2: each channel dispatched separately (per-channel try/except isolation)."""
    channels = {
        "UC_G2_CH004A": ["DDDDDDDDD01"],
        "UC_G2_CH005A": ["EEEEEEEEE01"],
    }
    _setup_channels(tmp_path, channels)

    registry = {
        "ch4": MagicMock(channel_id="UC_G2_CH004A"),
        "ch5": MagicMock(channel_id="UC_G2_CH005A"),
    }

    dispatch_calls: list[dict] = []
    call_count = 0

    def fake_dispatch(**kwargs):
        nonlocal call_count
        call_count += 1
        dispatch_calls.append({"video_ids": kwargs.get("video_ids")})

    alias_map = {"ch4": "UC_G2_CH004A", "ch5": "UC_G2_CH005A"}

    with patch("tube_scout.cli.collect.resolve_project", return_value=_mock_mgr(tmp_path)), \
         patch("tube_scout.cli.collect.resolve_alias_to_channel_id",
               side_effect=lambda a: alias_map[a]), \
         patch("tube_scout.cli.collect.dispatch_audio_fingerprint", side_effect=fake_dispatch), \
         patch("tube_scout.services.auth.load_registry", return_value=registry), \
         patch("tube_scout.storage.content_db.migrate_to_v3"):
        runner.invoke(app, ["collect", "audio", "--all-channels"])

    # Each channel should be dispatched separately
    assert call_count >= 2, f"Expected >=2 dispatch calls, got {call_count}"
