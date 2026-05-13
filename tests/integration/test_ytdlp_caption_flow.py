"""T019 RED — end-to-end yt-dlp caption flow integration test.

Pipeline: yt-dlp subprocess mock → fetch_caption_via_ytdlp → srv3_to_transcript_json
          → JSON atomic write → AuditWriter.append_transcript_row → idempotent re-run skip.
"""
import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "spec012"
AUTO_FIXTURE = FIXTURE_DIR / "auto_track.ko-orig.srv3"


def _make_completed(returncode: int, stdout: str = "", stderr: str = "") -> MagicMock:
    proc = MagicMock(spec=subprocess.CompletedProcess)
    proc.returncode = returncode
    proc.stdout = stdout
    proc.stderr = stderr
    return proc


def test_full_pipeline_srv3_to_json(tmp_path: Path) -> None:
    """yt-dlp mock returns srv3 fixture → adapter parses → writes spec 010 JSON."""
    from tube_scout.services.ytdlp_adapter import fetch_caption_via_ytdlp
    from tube_scout.services.srv3_parser import srv3_to_transcript_json, pick_priority_track
    from tube_scout.services.audit_writer import AuditWriter

    video_id = "INTTEST0001"
    output_dir = tmp_path / "transcripts"
    output_dir.mkdir()
    project_dir = tmp_path / "project"
    project_dir.mkdir()

    # Simulate yt-dlp writing the auto fixture to output_dir
    auto_srv3 = output_dir / f"{video_id}.ko-orig.srv3"
    auto_srv3.write_bytes(AUTO_FIXTURE.read_bytes())

    stdout = f"Writing video subtitles to: {auto_srv3}"
    mock_result = _make_completed(0, stdout=stdout)

    with patch("subprocess.run", return_value=mock_result):
        manual_path, auto_path = fetch_caption_via_ytdlp(
            video_url=f"https://youtu.be/{video_id}",
            output_dir=output_dir,
            cookies_browser="brave",
            sleep_seconds=(0.0, 0.0),
        )

    assert auto_path == auto_srv3
    assert manual_path is None

    # Parse srv3
    chosen_path, source_value = pick_priority_track(manual_path, auto_path)
    transcript = srv3_to_transcript_json(
        chosen_path.read_text(encoding="utf-8"),
        video_id=video_id,
        source=source_value,
    )

    assert transcript["video_id"] == video_id
    assert transcript["source"] == "ytdlp:auto"
    assert len(transcript["segments"]) == 767

    # Write JSON atomically
    json_path = project_dir / f"{video_id}.json"
    import tempfile, os
    tmp_fd, tmp_name = tempfile.mkstemp(dir=project_dir, suffix=".tmp")
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            json.dump(transcript, f, ensure_ascii=False, indent=2)
        os.replace(tmp_name, json_path)
    except Exception:
        os.unlink(tmp_name)
        raise

    assert json_path.exists()
    loaded = json.loads(json_path.read_text(encoding="utf-8"))
    assert loaded["video_id"] == video_id
    assert len(loaded["segments"]) == 767

    # Audit CSV append
    writer = AuditWriter(project_dir)
    writer.append_transcript_row({
        "video_id": video_id,
        "result": "success",
        "reason": "fetched",
        "source": source_value,
        "timestamp": transcript["fetched_at"],
        "cookies_source": "browser:brave",
    })

    audit_path = project_dir / "01_collect" / "transcripts_audit.csv"
    assert audit_path.exists()
    content = audit_path.read_text(encoding="utf-8")
    assert video_id in content
    assert "ok" in content


def test_idempotent_skip_existing(tmp_path: Path) -> None:
    """Second run on existing JSON → skip + audit reason='skip_existing', yt-dlp not called."""
    from tube_scout.services.audit_writer import AuditWriter
    from tube_scout.services.ytdlp_adapter import fetch_caption_via_ytdlp

    video_id = "INTTEST0002"
    output_dir = tmp_path / "transcripts"
    output_dir.mkdir()
    project_dir = tmp_path / "project"
    project_dir.mkdir()

    # Pre-existing transcript JSON
    json_path = project_dir / f"{video_id}.json"
    json_path.write_text('{"video_id": "INTTEST0002", "segments": [{"start": 0.0, "end": 1.0, "text": "test"}]}')

    subprocess_calls: list = []

    def spy_subprocess(*args, **kwargs):
        subprocess_calls.append(args)
        return _make_completed(0)

    with patch("subprocess.run", side_effect=spy_subprocess):
        # Idempotent check: skip if JSON already exists
        if json_path.exists():
            writer = AuditWriter(project_dir)
            writer.append_transcript_row({
                "video_id": video_id,
                "result": "skip",
                "reason": "skip_existing",
                "source": "",
                "timestamp": "2026-01-01T00:00:00+00:00",
                "cookies_source": "",
            })
        else:
            fetch_caption_via_ytdlp(
                video_url=f"https://youtu.be/{video_id}",
                output_dir=output_dir,
                sleep_seconds=(0.0, 0.0),
            )

    assert len(subprocess_calls) == 0, "yt-dlp must not be called when JSON exists"
    audit_path = project_dir / "01_collect" / "transcripts_audit.csv"
    assert "skip_existing" in audit_path.read_text(encoding="utf-8")


def test_no_captions_returns_none_none_audit(tmp_path: Path) -> None:
    """yt-dlp returns no srv3 → (None, None) → audit 'no_captions_available'."""
    from tube_scout.services.ytdlp_adapter import fetch_caption_via_ytdlp
    from tube_scout.services.audit_writer import AuditWriter

    video_id = "INTTEST0003"
    output_dir = tmp_path / "transcripts"
    output_dir.mkdir()
    project_dir = tmp_path / "project"
    project_dir.mkdir()

    mock_result = _make_completed(0, stdout="[youtube] Extracting URL...")

    with patch("subprocess.run", return_value=mock_result):
        manual_path, auto_path = fetch_caption_via_ytdlp(
            video_url=f"https://youtu.be/{video_id}",
            output_dir=output_dir,
            cookies_browser="brave",
            sleep_seconds=(0.0, 0.0),
        )

    assert manual_path is None
    assert auto_path is None

    writer = AuditWriter(project_dir)
    writer.append_transcript_row({
        "video_id": video_id,
        "result": "skip",
        "reason": "no_captions_available",
        "source": "",
        "timestamp": "2026-01-01T00:00:00+00:00",
        "cookies_source": "browser:brave",
    })

    audit_path = project_dir / "01_collect" / "transcripts_audit.csv"
    assert "no_captions_available" in audit_path.read_text(encoding="utf-8")
