"""T036 RED — integration test for collect ingest --force full cycle.

spec 018 US3 — fixture archive (US1/US2 complete state) + retry_pending.json
with 2 seeded failure entries → --force call verifies:
(a) all transcript json mtime updated (reprocessed)
(b) DB row count unchanged (PK uniqueness)
(c) retry_pending.json updated with new results (seeded failures resolved/updated)
(d) transcribe_audio and extract_chromaprint_fingerprint called for all videos

Uses spec018_mini_archive fixture (3 synthetic mp4). ASR and fingerprint mocked.
"""

from __future__ import annotations

import json
import sqlite3
import time
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

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


def _seed_retry_pending(retry_path: Path, video_ids: list[str]) -> None:
    """Seed retry_pending.json with given video_ids as failed entries."""
    entries = [
        {
            "video_id": vid,
            "title": vid,
            "failed_stage": "transcript",
            "failure_reason": "seeded_failure",
            "attempt_count": 1,
            "last_attempt_at": "2026-05-16T00:00:00+00:00",
        }
        for vid in video_ids
    ]
    manifest = {
        "schema_version": 1,
        "alias": "nursing",
        "entries": entries,
        "updated_at": "2026-05-16T00:00:00+00:00",
    }
    retry_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")


@pytest.fixture
def pre_populated_env(tmp_path: Path):
    """US1/US2 complete state: all 3 videos have transcript+fingerprint."""
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

    # Simulate first call: persist all
    for vid in video_ids:
        json_path = transcript_dir / f"{vid}.json"
        json_path.write_text("{}", encoding="utf-8")
        with sqlite3.connect(str(db_path)) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO audio_fingerprint "
                "(video_id, fingerprint, duration, extracted_at) VALUES (?, ?, ?, ?)",
                (vid, b"AAAA", 5.0, "2026-05-16T00:00:00+00:00"),
            )

    # Seed retry_pending with 2 failure entries (video_ids 0 and 1)
    retry_path = work_channel / "retry_pending.json"
    _seed_retry_pending(retry_path, video_ids[:2])

    return {
        "mp4_video_id_map": mp4_video_id_map,
        "work_channel": work_channel,
        "transcript_dir": transcript_dir,
        "db_path": db_path,
        "video_ids": video_ids,
        "retry_path": retry_path,
    }


class TestForceFullCycle:
    """T036 — --force: reprocesses all, updates retry_pending, PK uniqueness."""

    def test_force_calls_transcribe_for_all_videos(
        self, pre_populated_env: dict
    ) -> None:
        """force=True: transcribe_audio called for all 3 videos (no skip)."""
        from tube_scout.services.audit_writer import AuditWriter
        from tube_scout.services.unified_ingest import _run_transcript_and_fingerprint

        env = pre_populated_env
        audit = AuditWriter(env["work_channel"])
        asr_result = _make_mock_asr_result()

        with (
            patch("tube_scout.services.unified_ingest.extract_wav_16k_mono"),
            patch(
                "tube_scout.services.unified_ingest.transcribe_audio",
                return_value=asr_result,
            ) as mock_asr,
            patch(
                "tube_scout.services.unified_ingest.extract_chromaprint_fingerprint",
                return_value=(b"BBBB", 5.0),
            ) as mock_fp,
        ):
            tr, fr = _run_transcript_and_fingerprint(
                env["mp4_video_id_map"],
                env["work_channel"],
                audit,
                transcript_dir=env["transcript_dir"],
                db_path=env["db_path"],
                force=True,
            )

        assert mock_asr.call_count == 3, (
            f"Expected 3 transcribe_audio calls with force=True, got {mock_asr.call_count}"
        )
        assert mock_fp.call_count == 3
        assert tr.skip_count == 0
        assert fr.skip_count == 0

    def test_force_transcript_mtime_updated(self, pre_populated_env: dict) -> None:
        """force=True: all transcript json files are rewritten (mtime updated)."""
        from tube_scout.services.audit_writer import AuditWriter
        from tube_scout.services.unified_ingest import _run_transcript_and_fingerprint

        env = pre_populated_env
        transcript_dir = env["transcript_dir"]
        mtimes_before = {
            p.name: p.stat().st_mtime_ns
            for p in transcript_dir.glob("*.json")
        }

        time.sleep(0.01)  # ensure clock advances

        audit = AuditWriter(env["work_channel"])
        asr_result = _make_mock_asr_result()

        with (
            patch("tube_scout.services.unified_ingest.extract_wav_16k_mono"),
            patch(
                "tube_scout.services.unified_ingest.transcribe_audio",
                return_value=asr_result,
            ),
            patch(
                "tube_scout.services.unified_ingest.extract_chromaprint_fingerprint",
                return_value=(b"BBBB", 5.0),
            ),
        ):
            _run_transcript_and_fingerprint(
                env["mp4_video_id_map"],
                env["work_channel"],
                audit,
                transcript_dir=transcript_dir,
                db_path=env["db_path"],
                force=True,
            )

        mtimes_after = {
            p.name: p.stat().st_mtime_ns
            for p in transcript_dir.glob("*.json")
        }
        for fname, mtime_before in mtimes_before.items():
            assert mtimes_after[fname] > mtime_before, (
                f"{fname} mtime not updated by --force reprocess"
            )

    def test_force_db_row_count_unchanged(self, pre_populated_env: dict) -> None:
        """force=True: DB row count stays == 3 (INSERT OR REPLACE PK uniqueness)."""
        from tube_scout.services.audit_writer import AuditWriter
        from tube_scout.services.unified_ingest import _run_transcript_and_fingerprint

        env = pre_populated_env
        db_path = env["db_path"]

        with sqlite3.connect(str(db_path)) as conn:
            count_before = conn.execute(
                "SELECT COUNT(*) FROM audio_fingerprint"
            ).fetchone()[0]

        audit = AuditWriter(env["work_channel"])
        asr_result = _make_mock_asr_result()

        with (
            patch("tube_scout.services.unified_ingest.extract_wav_16k_mono"),
            patch(
                "tube_scout.services.unified_ingest.transcribe_audio",
                return_value=asr_result,
            ),
            patch(
                "tube_scout.services.unified_ingest.extract_chromaprint_fingerprint",
                return_value=(b"BBBB", 5.0),
            ),
        ):
            _run_transcript_and_fingerprint(
                env["mp4_video_id_map"],
                env["work_channel"],
                audit,
                transcript_dir=env["transcript_dir"],
                db_path=db_path,
                force=True,
            )

        with sqlite3.connect(str(db_path)) as conn:
            count_after = conn.execute(
                "SELECT COUNT(*) FROM audio_fingerprint"
            ).fetchone()[0]

        assert count_before == count_after, (
            f"DB row count changed with --force: {count_before} → {count_after}"
        )

    def test_force_audit_reason_includes_forced_reprocess(
        self, pre_populated_env: dict
    ) -> None:
        """force=True: audit row with reason='forced_reprocess' is emitted."""
        from tube_scout.services.unified_ingest import ingest_unified

        env = pre_populated_env
        audit_writer = MagicMock()
        audit_writer.append_row = MagicMock()
        asr_result = _make_mock_asr_result()

        with (
            patch("tube_scout.services.unified_ingest.ingest_takeout") as mock_takeout,
            patch("tube_scout.services.unified_ingest.extract_wav_16k_mono"),
            patch(
                "tube_scout.services.unified_ingest.transcribe_audio",
                return_value=asr_result,
            ),
            patch(
                "tube_scout.services.unified_ingest.extract_chromaprint_fingerprint",
                return_value=(b"BBBB", 5.0),
            ),
        ):
            from tube_scout.services.takeout_ingest import IngestResult
            mock_takeout.return_value = IngestResult(
                channel_id="UCtest",
                channel_alias="nursing",
                total_videos=3,
                new_videos=0,
                high_confidence_mappings=3,
                medium_confidence_mappings=0,
                ambiguous_mappings=0,
                unmapped_filenames=0,
                ignored_csv_count=0,
                dry_run=False,
                mp4_present_count=3,
                mp4_absent_count=0,
                elapsed_seconds=0.0,
                mp4_video_id_map=env["mp4_video_id_map"],
            )

            ingest_unified(
                takeout_dir=_FIXTURE_ARCHIVE,
                channel_alias="nursing",
                db_path=env["db_path"],
                work_root=env["work_channel"].parent,
                audit_writer=audit_writer,
                force=True,
            )

        # Find forced_reprocess audit row
        forced_calls = [
            call
            for call in audit_writer.append_row.call_args_list
            if call.args[0] == "ingest_orchestrator"
            and call.args[1].get("reason") == "forced_reprocess"
        ]
        assert len(forced_calls) >= 1, (
            f"Expected at least 1 'forced_reprocess' audit row, "
            f"got 0. All reasons: "
            f"{[c.args[1].get('reason') for c in audit_writer.append_row.call_args_list if c.args[0] == 'ingest_orchestrator']}"
        )
