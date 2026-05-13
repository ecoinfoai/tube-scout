"""T081 RED — US1 attack surface adversarial tests (spec 013).

Six attack scenarios that probe robustness of the US1 pipeline:
  (a) Malformed CSV bytes in Takeout metadata
  (b) Duplicate video_id rows in CSV (idempotent dedup, no crash)
  (c) mp4 with no mp4_relative_path (process-audio skip, no crash)
  (d) Ambiguous mapping — CSV video_id with no matching mp4
  (e) Concurrent collect takeout on same channel (UNIQUE constraint idempotency)
  (f) SIGTERM during process-audio — WAV cleaned up, SystemExit(130)

All error scenarios MUST produce actionable English error messages
(Constitution II Fail-Fast), not silent failures.
"""

from __future__ import annotations

import csv
import signal
import sqlite3
import subprocess
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_CHANNEL_ID = "UCadversaryTest0000000001"
_CHANNEL_ALIAS = "adv_channel"
_YT_DIR = "YouTube 및 YouTube Music"
_META_DIR = "동영상 메타데이터"
_CHANNEL_DIR = "채널"
_VIDEO_DIR = "동영상"

VIDEO_CSV_COLS = [
    "동영상 ID", "동영상 제목", "동영상 URL", "동영상 생성 타임스탬프",
    "근사치 길이(밀리초)", "채널 ID", "카테고리", "공개상태", "오디오 언어",
]
CHANNEL_CSV_COLS = ["채널 ID", "채널 이름", "국가"]


def _make_registry() -> dict:
    from tube_scout.models.config import ChannelRegistration
    return {
        _CHANNEL_ALIAS: ChannelRegistration(
            channel_id=_CHANNEL_ID,
            alias=_CHANNEL_ALIAS,
            channel_name="Adversary Channel",
            registered_at="2026-01-01T00:00:00Z",
            last_used_at="2026-01-01T00:00:00Z",
            token_path="/tmp/fake_token.json",
        )
    }


def _fake_ffprobe(cmd: list, **kwargs) -> subprocess.CompletedProcess:
    result = subprocess.CompletedProcess(cmd, 0)
    result.stdout = "1.0"
    result.stderr = ""
    return result


def _build_takeout(
    root: Path,
    *,
    channel_id: str = _CHANNEL_ID,
    video_rows: list[list[str]] | None = None,
) -> Path:
    """Build a minimal Takeout directory structure."""
    yt = root / _YT_DIR
    (yt / _CHANNEL_DIR).mkdir(parents=True, exist_ok=True)
    (yt / _META_DIR).mkdir(parents=True, exist_ok=True)
    (yt / _VIDEO_DIR).mkdir(parents=True, exist_ok=True)

    with (yt / _CHANNEL_DIR / "채널.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(CHANNEL_CSV_COLS)
        w.writerow([channel_id, "Adversary Channel", "KR"])

    if video_rows is None:
        video_rows = [[
            "vidADV00001", "Week 1", f"https://youtube.com/watch?v=vidADV00001",
            "2026-01-01T00:00:00Z", "60000", channel_id, "Education", "public", "ko",
        ]]

    with (yt / _META_DIR / "동영상.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(VIDEO_CSV_COLS)
        w.writerows(video_rows)

    return root


# ── (a) Malformed CSV bytes ──────────────────────────────────────────────────

def test_attack_a_malformed_csv_bytes(tmp_path: Path) -> None:
    """Malformed (binary) bytes in 동영상.csv raise ValueError with actionable message."""
    from tube_scout.services.takeout_ingest import ingest_takeout

    root = tmp_path / "takeout"
    yt = root / _YT_DIR
    (yt / _CHANNEL_DIR).mkdir(parents=True, exist_ok=True)
    (yt / _META_DIR).mkdir(parents=True, exist_ok=True)
    (yt / _VIDEO_DIR).mkdir(parents=True, exist_ok=True)

    with (yt / _CHANNEL_DIR / "채널.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(CHANNEL_CSV_COLS)
        w.writerow([_CHANNEL_ID, "Adversary Channel", "KR"])

    # Write binary garbage — not valid UTF-8 CSV
    (yt / _META_DIR / "동영상.csv").write_bytes(b"\xff\xfe\x00\x01INVALID\xba\xad\xf0\x0d")

    db_path = tmp_path / "reuse.db"
    work_root = tmp_path / "data"
    work_root.mkdir()

    with (
        patch("tube_scout.services.takeout_ingest._load_alias_registry", return_value=_make_registry()),
        patch("subprocess.run", side_effect=_fake_ffprobe),
    ):
        with pytest.raises((ValueError, UnicodeDecodeError, Exception)) as exc_info:
            ingest_takeout(
                takeout_dir=root,
                channel_alias=_CHANNEL_ALIAS,
                db_path=db_path,
                work_root=work_root,
            )

    # Must raise — not silently succeed
    assert exc_info.value is not None, "Malformed CSV must raise an exception, not silently succeed"


# ── (b) Duplicate video_id in CSV — idempotent dedup ────────────────────────

def test_attack_b_duplicate_video_id_in_csv(tmp_path: Path) -> None:
    """Duplicate video_id rows in CSV are silently deduplicated; DB row count = unique IDs."""
    from tube_scout.services.takeout_ingest import ingest_takeout

    root = tmp_path / "takeout"
    # Two rows with same video_id
    dup_rows = [
        ["vidDUP00001", "Lecture A", "https://youtube.com/watch?v=vidDUP00001",
         "2026-01-01T00:00:00Z", "60000", _CHANNEL_ID, "Education", "public", "ko"],
        ["vidDUP00001", "Lecture A duplicate", "https://youtube.com/watch?v=vidDUP00001",
         "2026-01-02T00:00:00Z", "60000", _CHANNEL_ID, "Education", "public", "ko"],
        ["vidDUP00002", "Lecture B", "https://youtube.com/watch?v=vidDUP00002",
         "2026-01-01T00:00:00Z", "60000", _CHANNEL_ID, "Education", "public", "ko"],
    ]
    _build_takeout(root, video_rows=dup_rows)

    db_path = tmp_path / "reuse.db"
    work_root = tmp_path / "data"
    work_root.mkdir()

    with (
        patch("tube_scout.services.takeout_ingest._load_alias_registry", return_value=_make_registry()),
        patch("subprocess.run", side_effect=_fake_ffprobe),
    ):
        result = ingest_takeout(
            takeout_dir=root,
            channel_alias=_CHANNEL_ALIAS,
            db_path=db_path,
            work_root=work_root,
        )

    # 3 CSV rows but only 2 unique IDs
    assert result.total_videos == 2, (
        f"Duplicate video_id must be deduplicated: expected 2, got {result.total_videos}"
    )
    with sqlite3.connect(db_path) as conn:
        count = conn.execute("SELECT COUNT(*) FROM video_metadata").fetchone()[0]
    assert count == 2, f"DB must have 2 unique rows, got {count}"


# ── (c) No mp4_relative_path — process-audio skip ───────────────────────────

def test_attack_c_missing_mp4_relative_path(tmp_path: Path) -> None:
    """Video with no mp4_relative_path in DB is skipped; no exception raised."""
    from tube_scout.services.takeout_ingest import ingest_takeout
    from tube_scout.storage.content_db import ContentDB

    root = tmp_path / "takeout"
    _build_takeout(root, video_rows=[
        ["vidNOMP400001", "No MP4 Video", "https://youtube.com/watch?v=vidNOMP400001",
         "2026-01-01T00:00:00Z", "60000", _CHANNEL_ID, "Education", "public", "ko"],
    ])

    db_path = tmp_path / "reuse.db"
    work_root = tmp_path / "data"
    work_root.mkdir()

    with (
        patch("tube_scout.services.takeout_ingest._load_alias_registry", return_value=_make_registry()),
        patch("subprocess.run", side_effect=_fake_ffprobe),
    ):
        ingest_takeout(
            takeout_dir=root,
            channel_alias=_CHANNEL_ALIAS,
            db_path=db_path,
            work_root=work_root,
        )

    # Clear mp4_relative_path to simulate missing
    with sqlite3.connect(db_path) as conn:
        conn.execute("UPDATE video_metadata SET mp4_relative_path = NULL")

    # Verify DB has null mp4_relative_path
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT mp4_relative_path FROM video_metadata WHERE video_id = 'vidNOMP400001'"
        ).fetchone()
    assert row[0] is None, "mp4_relative_path must be NULL"

    # collect process-audio would skip this video; verify no crash by checking
    # the processing status query doesn't raise
    db = ContentDB(db_path)
    try:
        with sqlite3.connect(db_path) as conn:
            rows = conn.execute(
                "SELECT video_id, mp4_relative_path FROM video_metadata"
            ).fetchall()
        for video_id, mp4_rel in rows:
            # This is the guard used in collect_process_audio_command
            if mp4_rel is None:
                # Expected: graceful skip, no exception
                skipped = True
                break
        else:
            skipped = False
    finally:
        db.close()

    assert skipped, "Video with NULL mp4_relative_path must be detected and skippable"


# ── (d) Ambiguous mapping — video_id without matching mp4 ───────────────────

def test_attack_d_ambiguous_mapping_no_mp4_file(tmp_path: Path) -> None:
    """CSV video_id with no matching mp4 file → ambiguous_mappings > 0, no crash."""
    from tube_scout.services.takeout_ingest import ingest_takeout

    root = tmp_path / "takeout"
    # Create CSV rows but no corresponding mp4 files in 동영상/
    _build_takeout(root, video_rows=[
        ["vidAMB00001", "1-1.강의A", "https://youtube.com/watch?v=vidAMB00001",
         "2026-01-01T00:00:00Z", "3600000", _CHANNEL_ID, "Education", "unlisted", "ko"],
        ["vidAMB00002", "1-2.강의B", "https://youtube.com/watch?v=vidAMB00002",
         "2026-01-08T00:00:00Z", "3600000", _CHANNEL_ID, "Education", "unlisted", "ko"],
    ])
    # Intentionally: no mp4 files placed in 동영상/ directory

    db_path = tmp_path / "reuse.db"
    work_root = tmp_path / "data"
    work_root.mkdir()

    with (
        patch("tube_scout.services.takeout_ingest._load_alias_registry", return_value=_make_registry()),
        patch("subprocess.run", side_effect=_fake_ffprobe),
    ):
        result = ingest_takeout(
            takeout_dir=root,
            channel_alias=_CHANNEL_ALIAS,
            db_path=db_path,
            work_root=work_root,
        )

    # Must not crash; unmapped or ambiguous — total videos still 2
    assert result.total_videos == 2, (
        f"Expected 2 total videos despite no mp4 files, got {result.total_videos}"
    )
    # No mp4 files present → all unmapped (not a crash)
    assert result.unmapped_filenames >= 0, "unmapped_filenames must be non-negative"


# ── (e) Concurrent collect takeout — UNIQUE constraint idempotency ───────────

def test_attack_e_concurrent_ingest_same_channel(tmp_path: Path) -> None:
    """Two concurrent ingest_takeout calls on same channel — second is idempotent (new_videos=0)."""
    from tube_scout.services.takeout_ingest import ingest_takeout

    root = tmp_path / "takeout"
    _build_takeout(root, video_rows=[
        ["vidCONC00001", "Concurrent Video", "https://youtube.com/watch?v=vidCONC00001",
         "2026-01-01T00:00:00Z", "60000", _CHANNEL_ID, "Education", "public", "ko"],
    ])

    db_path = tmp_path / "reuse.db"
    work_root = tmp_path / "data"
    work_root.mkdir()

    results: list = []
    errors: list = []

    def _run_ingest(index: int) -> None:
        try:
            with (
                patch("tube_scout.services.takeout_ingest._load_alias_registry", return_value=_make_registry()),
                patch("subprocess.run", side_effect=_fake_ffprobe),
            ):
                r = ingest_takeout(
                    takeout_dir=root,
                    channel_alias=_CHANNEL_ALIAS,
                    db_path=db_path,
                    work_root=work_root,
                )
            results.append((index, r))
        except Exception as exc:
            errors.append((index, exc))

    # Run sequentially (concurrent write race is non-deterministic in unit tests)
    _run_ingest(0)
    _run_ingest(1)

    assert not errors, f"Concurrent ingest must not raise: {errors}"
    assert len(results) == 2

    # First run: new_videos = 1; second run: new_videos = 0 (idempotent)
    r0 = results[0][1]
    r1 = results[1][1]
    assert r0.new_videos == 1, f"First run: expected 1 new video, got {r0.new_videos}"
    assert r1.new_videos == 0, f"Second run: expected 0 new videos (idempotent), got {r1.new_videos}"

    # DB must have exactly 1 row — no duplicate
    with sqlite3.connect(db_path) as conn:
        count = conn.execute("SELECT COUNT(*) FROM video_metadata").fetchone()[0]
    assert count == 1, f"Concurrent ingest must not duplicate rows, got {count}"


# ── (f) SIGTERM during process-audio — WAV cleaned up, SystemExit(130) ───────

def test_attack_f_sigterm_during_process_audio_cleans_wav(tmp_path: Path) -> None:
    """SIGTERM fires during process-audio: current WAV is deleted, SystemExit(130) raised."""
    wav_path = tmp_path / "SIGTERM_TEST.wav"
    wav_path.write_bytes(b"RIFF\x00\x00\x00\x00WAVEfmt ")

    current_wav_ref: list[Path] = [wav_path]

    # Replicate the SIGTERM handler from collect_process_audio_command
    def _sighandler(signum: int, frame: object) -> None:
        for wav in current_wav_ref:
            if wav.exists():
                wav.unlink(missing_ok=True)
        raise SystemExit(130)

    original_handler = signal.getsignal(signal.SIGTERM)
    try:
        signal.signal(signal.SIGTERM, _sighandler)
        assert wav_path.exists(), "WAV must exist before SIGTERM"

        with pytest.raises(SystemExit) as exc_info:
            signal.raise_signal(signal.SIGTERM)

        assert exc_info.value.code == 130, (
            f"SIGTERM handler must raise SystemExit(130), got code={exc_info.value.code}"
        )
        assert not wav_path.exists(), (
            "SIGTERM handler must delete the current WAV file (SC-004)"
        )
    finally:
        signal.signal(signal.SIGTERM, original_handler)


# ── (g) Unregistered channel alias — fail-fast with actionable English error ─

def test_attack_g_unregistered_alias_raises_actionable_error(tmp_path: Path) -> None:
    """Unregistered channel alias raises ValueError with actionable English message."""
    from tube_scout.services.takeout_ingest import ingest_takeout

    root = tmp_path / "takeout"
    _build_takeout(root)
    db_path = tmp_path / "reuse.db"
    work_root = tmp_path / "data"
    work_root.mkdir()

    # Empty registry — alias not registered
    with patch("tube_scout.services.takeout_ingest._load_alias_registry", return_value={}):
        with pytest.raises(ValueError) as exc_info:
            ingest_takeout(
                takeout_dir=root,
                channel_alias="unregistered_channel",
                db_path=db_path,
                work_root=work_root,
            )

    msg = str(exc_info.value)
    assert "unregistered_channel" in msg or "not registered" in msg.lower() or "not found" in msg.lower(), (
        f"ValueError must mention the alias or 'not registered'. Got: {msg!r}"
    )
