"""T055 RED — _dispatch_ytdlp_transcripts 5 scenarios.

F-1 fix: stub was empty; must implement full pipeline:
  alias → channel_id → videos_meta.json → for each video:
    fetch_caption_via_ytdlp → srv3_to_transcript_json → atomic JSON write
    → audit_writer.append_transcript_row
"""
import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "spec012"
AUTO_FIXTURE = FIXTURE_DIR / "auto_track.ko-orig.srv3"


def _mock_mgr(project_dir: Path) -> MagicMock:
    mgr = MagicMock()
    mgr.project_dir = str(project_dir)
    return mgr


def _make_proc(returncode: int = 0, stdout: str = "", stderr: str = "") -> MagicMock:
    proc = MagicMock(spec=subprocess.CompletedProcess)
    proc.returncode = returncode
    proc.stdout = stdout
    proc.stderr = stderr
    return proc


def _write_videos_meta(channel_dir: Path, video_ids: list[str]) -> None:
    channel_dir.mkdir(parents=True, exist_ok=True)
    (channel_dir / "videos_meta.json").write_text(
        json.dumps([{"video_id": vid} for vid in video_ids]),
        encoding="utf-8",
    )


def test_dispatch_ytdlp_transcripts_normal_flow(tmp_path: Path) -> None:
    """Scenario 1: normal flow — alias resolved, video fetched, JSON written, audit row appended."""
    from tube_scout.cli.collect import _dispatch_ytdlp_transcripts
    from tube_scout.services.audit_writer import AuditWriter

    video_id = "VID0000001a"
    channel_id = "UC_T055_001"
    channel_dir = tmp_path / "01_collect" / "channels" / channel_id
    _write_videos_meta(channel_dir, [video_id])

    # Simulate yt-dlp writing srv3 file
    transcript_dir = tmp_path / "01_collect" / "transcripts"
    transcript_dir.mkdir(parents=True, exist_ok=True)
    auto_srv3 = transcript_dir / f"{video_id}.ko-orig.srv3"
    auto_srv3.write_bytes(AUTO_FIXTURE.read_bytes())
    stdout_str = f"Writing video subtitles to: {auto_srv3}"

    audit = AuditWriter(tmp_path)
    audit_rows: list[dict] = []
    original_append = audit.append_transcript_row

    def capture_row(row: dict) -> None:
        audit_rows.append(row)
        original_append(row)

    audit.append_transcript_row = capture_row  # type: ignore[method-assign]

    with patch(
        "tube_scout.cli.collect.resolve_alias_to_channel_id",
        return_value=channel_id,
    ), patch(
        "tube_scout.cli.collect.resolve_project",
        return_value=_mock_mgr(tmp_path),
    ), patch(
        "subprocess.run",
        return_value=_make_proc(stdout=stdout_str),
    ):
        _dispatch_ytdlp_transcripts(
            channel="nursing",
            audit_writer=audit,
            sleep_seconds=(0.0, 0.0),
        )

    assert len(audit_rows) >= 1
    assert any(r["video_id"] == video_id for r in audit_rows)
    assert any(r.get("result") in ("ok", "success") for r in audit_rows)

    json_path = tmp_path / "01_collect" / "transcripts" / f"{video_id}.json"
    assert json_path.exists(), f"Transcript JSON not written: {json_path}"
    transcript = json.loads(json_path.read_text(encoding="utf-8"))
    assert transcript["video_id"] == video_id
    assert len(transcript["segments"]) > 0


def test_dispatch_ytdlp_transcripts_unregistered_alias(tmp_path: Path) -> None:
    """Scenario 2: unregistered channel alias → KeyError → no yt-dlp calls."""
    from tube_scout.cli.collect import _dispatch_ytdlp_transcripts
    from tube_scout.services.audit_writer import AuditWriter

    subprocess_calls: list = []

    def spy_run(*args, **kwargs):
        subprocess_calls.append(args)
        return _make_proc()

    with patch(
        "tube_scout.cli.collect.resolve_alias_to_channel_id",
        side_effect=KeyError("unregistered"),
    ), patch(
        "tube_scout.cli.collect.resolve_project",
        return_value=_mock_mgr(tmp_path),
    ), patch("subprocess.run", side_effect=spy_run):
        with pytest.raises((KeyError, SystemExit)):
            _dispatch_ytdlp_transcripts(
                channel="unknown_alias",
                audit_writer=AuditWriter(tmp_path),
                sleep_seconds=(0.0, 0.0),
            )

    assert len(subprocess_calls) == 0, "yt-dlp must not be called for unregistered alias"


def test_dispatch_ytdlp_transcripts_no_captions_audit(tmp_path: Path) -> None:
    """Scenario 3: yt-dlp returns (None, None) → audit 'no_captions_available'."""
    from tube_scout.cli.collect import _dispatch_ytdlp_transcripts
    from tube_scout.services.audit_writer import AuditWriter

    video_id = "VID0000003a"
    channel_id = "UC_T055_003"
    channel_dir = tmp_path / "01_collect" / "channels" / channel_id
    _write_videos_meta(channel_dir, [video_id])

    audit = AuditWriter(tmp_path)

    # yt-dlp exits 0 but no srv3 files
    with patch(
        "tube_scout.cli.collect.resolve_alias_to_channel_id",
        return_value=channel_id,
    ), patch(
        "tube_scout.cli.collect.resolve_project",
        return_value=_mock_mgr(tmp_path),
    ), patch(
        "subprocess.run",
        return_value=_make_proc(stdout="[youtube] no subtitles"),
    ):
        _dispatch_ytdlp_transcripts(
            channel="nursing",
            audit_writer=audit,
            sleep_seconds=(0.0, 0.0),
        )

    audit_path = tmp_path / "01_collect" / "transcripts_audit.csv"
    assert audit_path.exists()
    content = audit_path.read_text(encoding="utf-8")
    assert video_id in content
    assert "no_captions" in content


def test_dispatch_ytdlp_transcripts_idempotent_skip(tmp_path: Path) -> None:
    """Scenario 4: existing JSON → skip, yt-dlp not called again."""
    from tube_scout.cli.collect import _dispatch_ytdlp_transcripts
    from tube_scout.services.audit_writer import AuditWriter

    video_id = "VID0000004a"
    channel_id = "UC_T055_004"
    channel_dir = tmp_path / "01_collect" / "channels" / channel_id
    _write_videos_meta(channel_dir, [video_id])

    # Pre-existing transcript
    transcript_dir = tmp_path / "01_collect" / "transcripts"
    transcript_dir.mkdir(parents=True, exist_ok=True)
    json_path = transcript_dir / f"{video_id}.json"
    json_path.write_text(
        json.dumps({"video_id": video_id, "segments": [{"start": 0.0, "end": 1.0, "text": "cached"}]}),
        encoding="utf-8",
    )

    subprocess_calls: list = []

    def spy_run(*args, **kwargs):
        subprocess_calls.append(args)
        return _make_proc()

    audit = AuditWriter(tmp_path)

    with patch(
        "tube_scout.cli.collect.resolve_alias_to_channel_id",
        return_value=channel_id,
    ), patch(
        "tube_scout.cli.collect.resolve_project",
        return_value=_mock_mgr(tmp_path),
    ), patch("subprocess.run", side_effect=spy_run):
        _dispatch_ytdlp_transcripts(
            channel="nursing",
            audit_writer=audit,
            sleep_seconds=(0.0, 0.0),
        )

    assert len(subprocess_calls) == 0, "yt-dlp must not be called when transcript JSON exists"

    audit_path = tmp_path / "01_collect" / "transcripts_audit.csv"
    assert audit_path.exists()
    content = audit_path.read_text(encoding="utf-8")
    assert "skip_existing" in content


def test_dispatch_ytdlp_transcripts_all_channels(tmp_path: Path) -> None:
    """Scenario 5: all_channels=True dispatches for every registered channel."""
    from tube_scout.cli.collect import _dispatch_ytdlp_transcripts
    from tube_scout.services.audit_writer import AuditWriter

    channels = {
        "ch1": "UC_T055_A01",
        "ch2": "UC_T055_A02",
    }
    # 11-char valid video IDs for each channel
    channel_video_ids = {
        "UC_T055_A01": "AAAAAAAAA01",
        "UC_T055_A02": "AAAAAAAAA02",
    }
    for alias, cid in channels.items():
        channel_dir = tmp_path / "01_collect" / "channels" / cid
        _write_videos_meta(channel_dir, [channel_video_ids[cid]])

    registry_mock = {alias: MagicMock(channel_id=cid) for alias, cid in channels.items()}

    transcript_dirs: list[Path] = []

    def spy_run(*args, **kwargs):
        return _make_proc(stdout="[youtube] no subtitles")

    audit = AuditWriter(tmp_path)

    with patch(
        "tube_scout.cli.collect.resolve_project",
        return_value=_mock_mgr(tmp_path),
    ), patch(
        "tube_scout.cli.collect.resolve_alias_to_channel_id",
        side_effect=lambda alias: channels[alias],
    ), patch(
        "tube_scout.services.auth.load_registry",
        return_value=registry_mock,
    ), patch("subprocess.run", side_effect=spy_run):
        _dispatch_ytdlp_transcripts(
            all_channels=True,
            audit_writer=audit,
            sleep_seconds=(0.0, 0.0),
        )

    audit_path = tmp_path / "01_collect" / "transcripts_audit.csv"
    assert audit_path.exists()
    content = audit_path.read_text(encoding="utf-8")
    # At least one channel's video processed
    processed = [vid for vid in channel_video_ids.values() if vid in content]
    assert len(processed) >= 1
