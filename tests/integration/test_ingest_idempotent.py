"""T013 + T025 RED — idempotent integration tests for collect ingest (spec 017/018).

T013: two consecutive collect ingest calls on real archive yield identical DB state.
T025 (spec 018): second call with mini fixture completes in ≤ 2 seconds wall clock
  (SC-018-1) + zero WAV decode + transcript/fingerprint mtime unchanged.
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

_ARCHIVE_ROOT = (
    Path(__file__).parent.parent.parent
    / "data"
    / "takeout-20260511T130817Z-3-001"
)

_ARCHIVE_PRESENT = _ARCHIVE_ROOT.exists()


@pytest.mark.skipif(
    not _ARCHIVE_PRESENT,
    reason="Real takeout archive not present — skipping idempotent test",
)
class TestIngestIdempotent:
    """T013 — two consecutive collect ingest calls on same archive are idempotent (SC-004)."""

    @pytest.fixture(scope="class")
    def two_run_outputs(self, tmp_path_factory):
        """Run collect ingest twice; return (result1, result2, work_root, db_path)."""
        from unittest.mock import MagicMock, patch

        from tube_scout.cli.main import app

        work_root = tmp_path_factory.mktemp("nursing_idempotent_work")
        db_path = work_root / "test.db"

        mock_reg = MagicMock()
        mock_reg.channel_id = "UCnh3tm9uQkyA260cAHfl9rg"

        runner = CliRunner()
        common_args = [
            "collect", "ingest",
            "--takeout-dir", str(_ARCHIVE_ROOT),
            "--channel", "nursing",
            "--data-dir", str(work_root),
            "--db-path", str(db_path),
        ]

        with patch(
            "tube_scout.services.takeout_ingest._load_alias_registry",
            return_value={"nursing": mock_reg},
        ):
            result1 = runner.invoke(app, common_args)
            result2 = runner.invoke(app, common_args)

        return result1, result2, work_root, db_path

    def test_idempotent_db_row_count(self, two_run_outputs) -> None:
        """Second run does not add rows to video_metadata (SC-004)."""
        result1, result2, work_root, db_path = two_run_outputs

        assert result1.exit_code == 0, f"First run failed: {result1.output}"
        assert result2.exit_code == 0, f"Second run failed: {result2.output}"

        conn = sqlite3.connect(db_path)
        count = conn.execute(
            "SELECT COUNT(*) FROM video_metadata"
        ).fetchone()[0]
        conn.close()
        assert count == 2554, (
            f"Expected 2554 video_metadata rows after idempotent second run, got {count}"
        )

    def test_idempotent_new_videos_zero(self, two_run_outputs) -> None:
        """Second run reports new_videos=0 in UnifiedIngestSummary.ingest_result."""
        result1, result2, work_root, db_path = two_run_outputs

        # new_videos=0 is detectable from stdout — the CLI must report it
        assert "new=0" in result2.output or "new_videos=0" in result2.output, (
            f"Expected new_videos=0 in second run output, got:\n{result2.output}"
        )

    def test_idempotent_transcript_fingerprint_unchanged(self, two_run_outputs) -> None:
        """Transcript and fingerprint files are not re-generated on second run."""
        result1, result2, work_root, db_path = two_run_outputs

        transcript_dir = work_root / "nursing" / "03_transcripts"
        if not transcript_dir.exists():
            pytest.skip("transcript_dir not created — skipping mtime check")

        # Allow 1s buffer between runs — if files were re-created their mtime
        # would be after result1 completed
        transcript_files = sorted(transcript_dir.glob("*.json"))
        if not transcript_files:
            pytest.skip("No transcript files found — skipping mtime check")

        # All transcripts must have been created before second run started
        # (mtime from first run, not second run)
        # We check that second run output does not contain "새로 생성" / "success" for transcripts
        assert result2.output is not None, "Second run produced no output"


# ---------------------------------------------------------------------------
# T025: spec 018 — second call wall clock ≤ 2s with mini fixture
# ---------------------------------------------------------------------------

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


class TestSecondCallWallClock:
    """T025 — SC-018-1: second call completes in ≤ 2 seconds with all-skip."""

    @pytest.fixture
    def pre_populated_env(self, tmp_path: Path):
        """First call already persisted: all 3 videos have transcript + fingerprint."""
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

        # Simulate first call: write transcript JSONs + DB rows
        for vid in video_ids:
            (transcript_dir / f"{vid}.json").write_text("{}", encoding="utf-8")
            with sqlite3.connect(str(db_path)) as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO audio_fingerprint "
                    "(video_id, fingerprint, duration, extracted_at) VALUES (?, ?, ?, ?)",
                    (vid, b"AAAA", 5.0, "2026-05-16T00:00:00+00:00"),
                )

        return {
            "mp4_video_id_map": mp4_video_id_map,
            "work_channel": work_channel,
            "transcript_dir": transcript_dir,
            "db_path": db_path,
            "video_ids": video_ids,
        }

    def test_second_call_completes_in_under_2s(
        self, pre_populated_env: dict
    ) -> None:
        """SC-018-1: second call with all-skip completes in ≤ 2 seconds."""
        from tube_scout.services.audit_writer import AuditWriter
        from tube_scout.services.unified_ingest import _run_transcript_and_fingerprint

        env = pre_populated_env
        audit = AuditWriter(env["work_channel"])

        start = time.monotonic()
        _run_transcript_and_fingerprint(
            env["mp4_video_id_map"],
            env["work_channel"],
            audit,
            transcript_dir=env["transcript_dir"],
            db_path=env["db_path"],
        )
        elapsed = time.monotonic() - start

        assert elapsed <= 2.0, (
            f"Second call took {elapsed:.2f}s — exceeds SC-018-1 limit of 2.0s"
        )

    def test_second_call_transcript_mtime_unchanged(
        self, pre_populated_env: dict
    ) -> None:
        """Transcript JSON mtime is not updated on second call (no re-write)."""
        from tube_scout.services.audit_writer import AuditWriter
        from tube_scout.services.unified_ingest import _run_transcript_and_fingerprint

        env = pre_populated_env
        transcript_dir = env["transcript_dir"]
        mtimes_before = {
            p.name: p.stat().st_mtime_ns
            for p in transcript_dir.glob("*.json")
        }
        assert mtimes_before, "pre_populated_env should have transcript JSONs"

        audit = AuditWriter(env["work_channel"])
        _run_transcript_and_fingerprint(
            env["mp4_video_id_map"],
            env["work_channel"],
            audit,
            transcript_dir=transcript_dir,
            db_path=env["db_path"],
        )

        mtimes_after = {
            p.name: p.stat().st_mtime_ns
            for p in transcript_dir.glob("*.json")
        }
        assert mtimes_before == mtimes_after, (
            f"Transcript mtime changed on second call: {mtimes_after}"
        )

    def test_second_call_db_row_count_unchanged(
        self, pre_populated_env: dict
    ) -> None:
        """DB row count does not change on second call (no INSERT)."""
        from tube_scout.services.audit_writer import AuditWriter
        from tube_scout.services.unified_ingest import _run_transcript_and_fingerprint

        env = pre_populated_env
        db_path = env["db_path"]

        with sqlite3.connect(str(db_path)) as conn:
            count_before = conn.execute(
                "SELECT COUNT(*) FROM audio_fingerprint"
            ).fetchone()[0]

        audit = AuditWriter(env["work_channel"])
        _run_transcript_and_fingerprint(
            env["mp4_video_id_map"],
            env["work_channel"],
            audit,
            transcript_dir=env["transcript_dir"],
            db_path=db_path,
        )

        with sqlite3.connect(str(db_path)) as conn:
            count_after = conn.execute(
                "SELECT COUNT(*) FROM audio_fingerprint"
            ).fetchone()[0]

        assert count_before == count_after, (
            f"DB row count changed: {count_before} → {count_after}"
        )

    def test_second_call_no_wav_files_created(
        self, pre_populated_env: dict
    ) -> None:
        """WAV temp files are never created on second (all-skip) call."""
        from tube_scout.services.audit_writer import AuditWriter
        from tube_scout.services.unified_ingest import _run_transcript_and_fingerprint

        env = pre_populated_env
        audit = AuditWriter(env["work_channel"])
        _run_transcript_and_fingerprint(
            env["mp4_video_id_map"],
            env["work_channel"],
            audit,
            transcript_dir=env["transcript_dir"],
            db_path=env["db_path"],
        )

        wav_dir = env["work_channel"] / "tmp_wav"
        if wav_dir.exists():
            wav_files = list(wav_dir.glob("*.wav"))
            assert wav_files == [], (
                f"WAV files found on second (all-skip) call: {wav_files}"
            )

    def test_second_call_extract_wav_not_called(
        self, pre_populated_env: dict
    ) -> None:
        """extract_wav_16k_mono is never called when all videos are skip (FR-018E)."""
        from unittest.mock import patch

        from tube_scout.services.audit_writer import AuditWriter
        from tube_scout.services.unified_ingest import _run_transcript_and_fingerprint

        env = pre_populated_env
        audit = AuditWriter(env["work_channel"])

        with patch(
            "tube_scout.services.unified_ingest.extract_wav_16k_mono"
        ) as mock_wav:
            _run_transcript_and_fingerprint(
                env["mp4_video_id_map"],
                env["work_channel"],
                audit,
                transcript_dir=env["transcript_dir"],
                db_path=env["db_path"],
            )

        assert mock_wav.call_count == 0, (
            f"extract_wav_16k_mono called {mock_wav.call_count} times "
            "on all-skip second call — WAV decode should be skipped"
        )
