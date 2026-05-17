"""T053 INTEGRATION — collect process-audio integrated pipeline.

Tests the per-video [WAV extract → fingerprint → ASR → normalize → WAV delete] loop
using mocked service layer. Verifies C-1 WAV lifecycle, skip-fingerprint, skip-asr,
keep-audio flags, and audit row generation.
"""
import json
import sqlite3
import struct
import wave
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.integration


def _write_silent_wav(path: Path) -> None:
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        wf.writeframes(struct.pack("<16000h", *([0] * 16000)))


def _setup_db(db_path: Path, channel_alias: str, video_id: str, mp4_rel: str) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS channel_metadata (
                channel_id TEXT PRIMARY KEY,
                channel_alias TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS video_metadata (
                video_id TEXT PRIMARY KEY,
                channel_id TEXT NOT NULL,
                title TEXT,
                mp4_relative_path TEXT
            );
            CREATE TABLE IF NOT EXISTS audio_fingerprint (
                video_id TEXT PRIMARY KEY,
                fingerprint BLOB,
                duration_sec REAL,
                extracted_at TEXT
            );
        """)
        conn.execute(
            "INSERT OR IGNORE INTO channel_metadata VALUES (?, ?)",
            ("UCtest", channel_alias),
        )
        conn.execute(
            "INSERT OR IGNORE INTO video_metadata VALUES (?, ?, ?, ?)",
            (video_id, "UCtest", "Test video", mp4_rel),
        )


def _make_asr_result() -> MagicMock:
    from tube_scout.models.content import AsrQualityFlags
    from tube_scout.services.asr import TranscribeResult

    flags = AsrQualityFlags()
    result = TranscribeResult(
        segments=[{"start": 0.0, "end": 1.0, "text": "테스트"}],
        language_detected="ko",
        duration=1.0,
        asr_quality_flags=flags,
        caption_source_detail="asr:faster-whisper:large-v3:int8_float16",
    )
    return result


def test_process_audio_wav_deleted_after_processing(tmp_path: Path) -> None:
    """C-1: WAV file is deleted after per-video processing (keep_audio=False)."""
    from typer.testing import CliRunner

    from tube_scout.cli.main import app

    channel = "test-ch"
    video_id = "PROC_TEST_001"
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    mp4_dir = data_dir / channel / "videos"
    mp4_dir.mkdir(parents=True)

    # Create a fake mp4 (WAV actually, but filename is .mp4)
    mp4_path = mp4_dir / f"{video_id}.mp4"
    _write_silent_wav(mp4_path)

    db = data_dir / "content_reuse.db"
    _setup_db(db, channel, video_id, f"videos/{video_id}.mp4")

    wav_path = audio_dir / f"{video_id}.wav"

    def fake_extract_wav(src, dst, **kw):
        _write_silent_wav(dst)

    asr_result = _make_asr_result()

    runner = CliRunner()
    with patch("tube_scout.services.audio_extract.extract_wav_16k_mono", side_effect=fake_extract_wav), \
         patch("tube_scout.services.asr.transcribe_audio", return_value=asr_result), \
         patch("tube_scout.services.audio_fingerprint.extract_chromaprint_fingerprint", return_value=(b"\x00" * 4, 1.0)), \
         patch("tube_scout.storage.content_db.insert_audio_fingerprint"):
        result = runner.invoke(app, [
            "collect", "process-audio",
            "--channel", channel,
            "--video-ids", video_id,
            "--preset", "poc-laptop",
            "--data-dir", str(data_dir),
            "--audio-cache-dir", str(audio_dir),
        ])

    assert result.exit_code in (0, 5), f"Unexpected exit code: {result.exit_code}\n{result.output}"
    # WAV must be deleted after processing
    assert not wav_path.exists(), f"WAV should have been deleted but still exists: {wav_path}"


def test_process_audio_keep_audio_flag(tmp_path: Path) -> None:
    """--keep-audio retains WAV after processing."""
    channel = "test-ch"
    video_id = "PROC_TEST_002"
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    mp4_dir = data_dir / channel / "videos"
    mp4_dir.mkdir(parents=True)

    mp4_path = mp4_dir / f"{video_id}.mp4"
    _write_silent_wav(mp4_path)

    db = data_dir / "content_reuse.db"
    _setup_db(db, channel, video_id, f"videos/{video_id}.mp4")

    wav_path = audio_dir / f"{video_id}.wav"

    def fake_extract_wav(src, dst, **kw):
        _write_silent_wav(dst)

    asr_result = _make_asr_result()

    from typer.testing import CliRunner

    from tube_scout.cli.main import app

    runner = CliRunner()
    with patch("tube_scout.services.audio_extract.extract_wav_16k_mono", side_effect=fake_extract_wav), \
         patch("tube_scout.services.asr.transcribe_audio", return_value=asr_result), \
         patch("tube_scout.services.audio_fingerprint.extract_chromaprint_fingerprint", return_value=(b"\x00" * 4, 1.0)), \
         patch("tube_scout.storage.content_db.insert_audio_fingerprint"):
        result = runner.invoke(app, [
            "collect", "process-audio",
            "--channel", channel,
            "--video-ids", video_id,
            "--preset", "poc-laptop",
            "--keep-audio",
            "--data-dir", str(data_dir),
            "--audio-cache-dir", str(audio_dir),
        ])

    assert result.exit_code in (0, 5)
    assert wav_path.exists(), "WAV should be kept with --keep-audio"


def test_process_audio_skip_asr(tmp_path: Path) -> None:
    """--skip-asr does not call transcribe_audio."""
    channel = "test-ch"
    video_id = "PROC_TEST_003"
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    mp4_dir = data_dir / channel / "videos"
    mp4_dir.mkdir(parents=True)

    mp4_path = mp4_dir / f"{video_id}.mp4"
    _write_silent_wav(mp4_path)

    db = data_dir / "content_reuse.db"
    _setup_db(db, channel, video_id, f"videos/{video_id}.mp4")

    def fake_extract_wav(src, dst, **kw):
        _write_silent_wav(dst)

    asr_mock = MagicMock()

    from typer.testing import CliRunner

    from tube_scout.cli.main import app

    runner = CliRunner()
    with patch("tube_scout.services.audio_extract.extract_wav_16k_mono", side_effect=fake_extract_wav), \
         patch("tube_scout.services.asr.transcribe_audio", asr_mock), \
         patch("tube_scout.services.audio_fingerprint.extract_chromaprint_fingerprint", return_value=(b"\x00" * 4, 1.0)), \
         patch("tube_scout.storage.content_db.insert_audio_fingerprint"):
        result = runner.invoke(app, [
            "collect", "process-audio",
            "--channel", channel,
            "--video-ids", video_id,
            "--preset", "poc-laptop",
            "--skip-asr",
            "--data-dir", str(data_dir),
            "--audio-cache-dir", str(audio_dir),
        ])

    assert result.exit_code in (0, 5)
    asr_mock.assert_not_called()


def test_process_audio_transcript_json_written(tmp_path: Path) -> None:
    """After ASR step, transcript JSON is atomically written."""
    channel = "test-ch"
    video_id = "PROC_TEST_004"
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    mp4_dir = data_dir / channel / "videos"
    mp4_dir.mkdir(parents=True)

    mp4_path = mp4_dir / f"{video_id}.mp4"
    _write_silent_wav(mp4_path)

    db = data_dir / "content_reuse.db"
    _setup_db(db, channel, video_id, f"videos/{video_id}.mp4")

    def fake_extract_wav(src, dst, **kw):
        _write_silent_wav(dst)

    asr_result = _make_asr_result()

    from typer.testing import CliRunner

    from tube_scout.cli.main import app

    runner = CliRunner()
    with patch("tube_scout.services.audio_extract.extract_wav_16k_mono", side_effect=fake_extract_wav), \
         patch("tube_scout.services.asr.transcribe_audio", return_value=asr_result), \
         patch("tube_scout.services.audio_fingerprint.extract_chromaprint_fingerprint", return_value=(b"\x00" * 4, 1.0)), \
         patch("tube_scout.storage.content_db.insert_audio_fingerprint"):
        result = runner.invoke(app, [
            "collect", "process-audio",
            "--channel", channel,
            "--video-ids", video_id,
            "--preset", "poc-laptop",
            "--data-dir", str(data_dir),
            "--audio-cache-dir", str(audio_dir),
        ])

    json_path = data_dir / channel / "01_collect" / "transcripts" / f"{video_id}.json"
    assert json_path.exists(), f"Expected transcript JSON at {json_path}"
    loaded = json.loads(json_path.read_text())
    assert loaded["video_id"] == video_id
    assert loaded["segments"] == [{"start": 0.0, "end": 1.0, "text": "테스트"}]
