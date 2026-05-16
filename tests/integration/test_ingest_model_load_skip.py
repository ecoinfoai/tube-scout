"""T026 RED — verify WhisperModel.__init__ is not called on all-skip second call.

FR-018E (§7): faster-whisper model loading is naturally avoided when transcribe_audio
is never called. Second call with all-skip should not trigger WhisperModel.__init__.
First call (with mocks for actual transcription) should call WhisperModel.__init__
to verify the spy is not a false positive.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

try:
    import faster_whisper  # noqa: F401
    _FASTER_WHISPER_AVAILABLE = True
except ImportError:
    _FASTER_WHISPER_AVAILABLE = False

_FIXTURE_ARCHIVE = (
    Path(__file__).parent.parent / "fixtures" / "spec018_mini_archive"
)

_V3_SQL = """
CREATE TABLE IF NOT EXISTS audio_fingerprint (
    video_id     TEXT PRIMARY KEY,
    fingerprint  BLOB NOT NULL,
    duration     REAL NOT NULL,
    extracted_at TEXT NOT NULL,
    source       TEXT NOT NULL DEFAULT 'fpcalc:1.6.0'
);
"""


def _make_mock_asr_result() -> MagicMock:
    result = MagicMock()
    result.caption_source_detail = "asr:faster-whisper:large-v3:int8_float16"
    result.language_detected = "ko"
    result.duration = 5.0
    result.segments = []
    result.asr_quality_flags = MagicMock()
    result.asr_quality_flags.model_dump.return_value = {
        "hallucination_repeat": False,
        "vad_over_truncated": False,
        "language_mismatch": False,
        "short_segments_excess": False,
        "silence_hallucination": False,
        "compression_ratio_violations": 0,
    }
    return result


@pytest.mark.skipif(
    not _FASTER_WHISPER_AVAILABLE,
    reason="faster_whisper not installed — run: uv sync --extra asr",
)
class TestModelLoadSkip:
    """T026 — WhisperModel.__init__ spy verifies model load avoidance (FR-018E)."""

    @pytest.fixture
    def env(self, tmp_path: Path):
        db_path = tmp_path / "test.db"
        with sqlite3.connect(str(db_path)) as conn:
            conn.executescript(_V3_SQL)

        alias = "nursing"
        work_channel = tmp_path / alias
        work_channel.mkdir()
        transcript_dir = work_channel / "02_analyze" / "transcripts"
        transcript_dir.mkdir(parents=True)

        mp4_dir = _FIXTURE_ARCHIVE / "YouTube and YouTube Music" / "videos"
        mp4_files = sorted(mp4_dir.glob("*.mp4"))
        video_ids = [f"VID0000{i+1}" for i in range(len(mp4_files))]
        mp4_video_id_map = {str(p): vid for p, vid in zip(mp4_files, video_ids)}

        return {
            "mp4_video_id_map": mp4_video_id_map,
            "work_channel": work_channel,
            "transcript_dir": transcript_dir,
            "db_path": db_path,
            "video_ids": video_ids,
        }

    def test_model_not_loaded_on_all_skip_call(self, env: dict) -> None:
        """WhisperModel.__init__ is NOT called when all videos are already processed."""
        from tube_scout.services.audit_writer import AuditWriter
        from tube_scout.services.unified_ingest import _run_transcript_and_fingerprint

        # Pre-populate: all videos already have transcript + fingerprint
        transcript_dir = env["transcript_dir"]
        db_path = env["db_path"]
        for vid in env["video_ids"]:
            (transcript_dir / f"{vid}.json").write_text("{}", encoding="utf-8")
            with sqlite3.connect(str(db_path)) as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO audio_fingerprint "
                    "(video_id, fingerprint, duration, extracted_at) VALUES (?, ?, ?, ?)",
                    (vid, b"AAAA", 5.0, "2026-05-16T00:00:00+00:00"),
                )

        audit = AuditWriter(env["work_channel"])
        whisper_init_call_count = 0

        def spy_whisper_init(self, *args, **kwargs):
            nonlocal whisper_init_call_count
            whisper_init_call_count += 1

        with patch(
            "faster_whisper.WhisperModel.__init__",
            spy_whisper_init,
        ):
            _run_transcript_and_fingerprint(
                env["mp4_video_id_map"],
                env["work_channel"],
                audit,
                transcript_dir=transcript_dir,
                db_path=db_path,
            )

        assert whisper_init_call_count == 0, (
            f"WhisperModel.__init__ called {whisper_init_call_count} times "
            "on all-skip second call — model load should be avoided"
        )

    def test_model_is_loaded_on_first_call_spy_not_false_positive(
        self, env: dict
    ) -> None:
        """WhisperModel.__init__ IS called on first call — confirms spy is working."""
        from tube_scout.services.audit_writer import AuditWriter
        from tube_scout.services.unified_ingest import _run_transcript_and_fingerprint

        whisper_init_call_count = 0

        def spy_whisper_init(self, *args, **kwargs):
            nonlocal whisper_init_call_count
            whisper_init_call_count += 1

        asr_result = _make_mock_asr_result()

        with (
            patch("faster_whisper.WhisperModel.__init__", spy_whisper_init),
            patch(
                "tube_scout.services.unified_ingest.transcribe_audio",
                return_value=asr_result,
            ) as mock_transcribe,
            patch(
                "tube_scout.services.unified_ingest.extract_wav_16k_mono"
            ),
            patch(
                "tube_scout.services.unified_ingest.extract_chromaprint_fingerprint",
                return_value=(b"AAAA", 5.0),
            ),
        ):
            audit = AuditWriter(env["work_channel"])
            _run_transcript_and_fingerprint(
                env["mp4_video_id_map"],
                env["work_channel"],
                audit,
                transcript_dir=env["transcript_dir"],
                db_path=env["db_path"],
            )
            # transcribe_audio was called (not skipped)
            assert mock_transcribe.call_count == len(env["mp4_video_id_map"]), (
                "transcribe_audio should be called for all videos on first call"
            )
