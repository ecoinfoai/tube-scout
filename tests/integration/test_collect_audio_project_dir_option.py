"""T058 RED — G-1: collect audio/fingerprint --project-dir option.

Verifies both commands accept --project-dir and use it instead of hard-coded "./projects".
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


def test_collect_audio_respects_project_dir_option(tmp_path: Path) -> None:
    """G-1: --project-dir <path> is used instead of hard-coded './projects'."""
    custom_project = tmp_path / "custom_projects"

    channel_id = "UC_G1_TEST01"
    channel_dir = custom_project / "01_collect" / "channels" / channel_id
    channel_dir.mkdir(parents=True)
    (channel_dir / "videos_meta.json").write_text(
        json.dumps([{"video_id": "VIDG1000001"}]), encoding="utf-8"
    )

    captured_project_dir: list[str] = []

    def fake_resolve(path_str, *args, **kwargs):
        captured_project_dir.append(path_str)
        return _mock_mgr(custom_project)

    dispatch_calls: list[dict] = []

    def fake_dispatch(**kwargs):
        dispatch_calls.append(kwargs)

    with patch("tube_scout.cli.collect.resolve_project", side_effect=fake_resolve), \
         patch("tube_scout.cli.collect.resolve_alias_to_channel_id", return_value=channel_id), \
         patch("tube_scout.cli.collect.dispatch_audio_fingerprint", side_effect=fake_dispatch), \
         patch("tube_scout.storage.content_db.migrate_to_v3"):
        result = runner.invoke(app, [
            "collect", "audio",
            "--channel", "nursing",
            "--project-dir", str(custom_project),
        ])

    assert result.exit_code in (0, 1), f"Unexpected exit: {result.exit_code}\n{result.output}"
    assert captured_project_dir, "resolve_project was not called"
    assert str(custom_project) in captured_project_dir[0], (
        f"resolve_project called with '{captured_project_dir[0]}', "
        f"expected path containing '{custom_project}'"
    )


def test_collect_fingerprint_respects_project_dir_option(tmp_path: Path) -> None:
    """G-1: collect fingerprint --project-dir <path> also uses custom path."""
    custom_project = tmp_path / "fp_custom"

    channel_id = "UC_G1_FP0001"
    channel_dir = custom_project / "01_collect" / "channels" / channel_id
    channel_dir.mkdir(parents=True)
    (channel_dir / "videos_meta.json").write_text(
        json.dumps([{"video_id": "VIDFP000001"}]), encoding="utf-8"
    )

    captured_project_dir: list[str] = []

    def fake_resolve(path_str, *args, **kwargs):
        captured_project_dir.append(path_str)
        return _mock_mgr(custom_project)

    with patch("tube_scout.cli.collect.resolve_project", side_effect=fake_resolve), \
         patch("tube_scout.cli.collect.resolve_alias_to_channel_id", return_value=channel_id), \
         patch("tube_scout.cli.collect.dispatch_audio_fingerprint"), \
         patch("tube_scout.storage.content_db.migrate_to_v3"):
        result = runner.invoke(app, [
            "collect", "fingerprint",
            "--channel", "nursing",
            "--project-dir", str(custom_project),
        ])

    assert result.exit_code in (0, 1), f"Unexpected exit: {result.exit_code}\n{result.output}"
    assert captured_project_dir
    assert str(custom_project) in captured_project_dir[0]


def test_collect_audio_default_project_dir_is_projects(tmp_path: Path) -> None:
    """G-1: Without --project-dir, default is './projects' (not CWD-relative breakage)."""
    channel_id = "UC_G1_DEF001"

    fake_project = tmp_path / "projects"
    channel_dir = fake_project / "01_collect" / "channels" / channel_id
    channel_dir.mkdir(parents=True)
    (channel_dir / "videos_meta.json").write_text(
        json.dumps([{"video_id": "VIDDEFAULT1"}]), encoding="utf-8"
    )

    called_with: list[str] = []

    def fake_resolve(path_str, *args, **kwargs):
        called_with.append(path_str)
        return _mock_mgr(fake_project)

    with patch("tube_scout.cli.collect.resolve_project", side_effect=fake_resolve), \
         patch("tube_scout.cli.collect.resolve_alias_to_channel_id", return_value=channel_id), \
         patch("tube_scout.cli.collect.dispatch_audio_fingerprint"), \
         patch("tube_scout.storage.content_db.migrate_to_v3"):
        runner.invoke(app, ["collect", "audio", "--channel", "nursing"])

    assert called_with, "resolve_project must be called"
    # Default must be './projects' (not empty string or None)
    assert called_with[0] == "./projects", (
        f"Default project-dir expected './projects', got '{called_with[0]}'"
    )
