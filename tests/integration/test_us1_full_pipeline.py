"""T080 RED — US1 full pipeline integration test (spec 013).

Runs the 4-stage pipeline against the 9-video Takeout fixture:
  1. collect takeout  (ingest_takeout service)
  2. collect process-audio --preset poc-laptop --skip-asr  (mock WAV/fpcalc)
  3. analyze content-reuse --mode M-nC2 --professor TestProf  (run_nc2_analysis)
  4. report content-reuse --format html  (render_professor_nc2_report)

Assertions:
  - HTML report generated under output_dir
  - SQLite tables fully populated
  - 8 audit CSV stage files present under 01_collect/
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

FIXTURE_TAKEOUT = Path(__file__).parent.parent / "fixtures" / "takeout_sample" / "Takeout"
_PROFESSOR = "TestProf"
_CHANNEL = "test_channel"
_CHANNEL_ID = "UCfakeAnonChan0123456789"

_FPCALC_STDOUT = "DURATION=1\nFINGERPRINT=AQADtFMSRUkiJdmEjzoqJI\n"


def _make_registry() -> dict:
    from tube_scout.models.config import ChannelRegistration
    return {
        _CHANNEL: ChannelRegistration(
            channel_id=_CHANNEL_ID,
            alias=_CHANNEL,
            channel_name="Test Channel",
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


def _fake_fpcalc(cmd: list, **kwargs) -> subprocess.CompletedProcess:
    result = subprocess.CompletedProcess(cmd, 0)
    result.stdout = _FPCALC_STDOUT
    result.stderr = ""
    return result


def _fake_ffmpeg_wav(src: Path, dst: Path, *, force: bool = False) -> None:
    """Mock WAV extraction — write a minimal valid WAV header stub."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(b"RIFF\x00\x00\x00\x00WAVEfmt ")


def _write_fake_transcripts(work_root: Path, video_ids: list[str]) -> None:
    """Write minimal transcript JSON for each video (skip-asr mode supplement)."""
    transcript_dir = work_root / _CHANNEL / "01_collect" / "transcripts"
    transcript_dir.mkdir(parents=True, exist_ok=True)
    for vid in video_ids:
        transcript = {
            "video_id": vid,
            "source": "asr:faster-whisper",
            "language": "ko",
            "duration": 1.0,
            "segments": [{"start": 0.0, "end": 1.0, "text": "테스트 강의 내용입니다."}],
            "asr_quality_flags": {},
            "fetched_at": "2026-05-13T00:00:00+00:00",
        }
        json_path = transcript_dir / f"{vid}.json"
        json_path.write_text(json.dumps(transcript, ensure_ascii=False, indent=2), encoding="utf-8")


@pytest.mark.slow
def test_us1_full_pipeline(tmp_path: Path) -> None:
    """US1 full pipeline: Takeout ingest → audio process → nC2 analyze → report."""
    from tube_scout.reporting.professor_nc2 import (
        render_professor_nc2_report,
    )
    from tube_scout.services.audit_writer import AuditWriter
    from tube_scout.services.nc2_matcher import run_nc2_analysis
    from tube_scout.services.professor_resolver import map_professor
    from tube_scout.services.takeout_ingest import ingest_takeout
    from tube_scout.storage.content_db import (
        ContentDB,
        insert_audio_fingerprint,
    )

    work_root = tmp_path / "data"
    work_root.mkdir()
    db_path = work_root / "content_reuse.db"
    # report output_dir aligned with work_root channel dir so audit CSV lands in 01_collect/
    channel_dir = work_root / _CHANNEL
    output_dir = channel_dir / "03_report"
    audio_cache = tmp_path / "audio_cache"
    audio_cache.mkdir()

    # ── Stage 1: collect takeout ─────────────────────────────────────────────
    with (
        patch("tube_scout.services.takeout_ingest._load_alias_registry", return_value=_make_registry()),
        patch("subprocess.run", side_effect=_fake_ffprobe),
    ):
        ingest_result = ingest_takeout(
            takeout_dir=FIXTURE_TAKEOUT,
            channel_alias=_CHANNEL,
            db_path=db_path,
            work_root=work_root,
        )

    assert ingest_result.total_videos == 9
    assert ingest_result.new_videos == 9

    # ── Stage 2: collect process-audio --preset poc-laptop --skip-asr ────────
    # Mock WAV extraction + fpcalc; skip ASR (write fake transcripts instead)
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT video_id FROM video_metadata WHERE channel_id = ?",
            (_CHANNEL_ID,),
        ).fetchall()
    video_ids = [r[0] for r in rows]
    assert len(video_ids) == 9

    db_obj = ContentDB(db_path)
    try:
        import datetime as _dt
        ts = _dt.datetime.now(tz=_dt.UTC).isoformat()
        fake_fp_bytes = b"\x00" * 128
        fake_fp_dur = 60.0
        for vid in video_ids:
            insert_audio_fingerprint(db_path, vid, fake_fp_bytes, fake_fp_dur, ts)
            db_obj.upsert_processing_status(
                vid, _CHANNEL_ID, "fingerprinted",
                fingerprinted_at=ts,
            )
    finally:
        db_obj.close()

    # Write fake transcripts (--skip-asr simulation)
    _write_fake_transcripts(work_root, video_ids)

    # Audit entries for audio_extract + fingerprint stages
    audit = AuditWriter(work_root / _CHANNEL)
    for vid in video_ids:
        audit.append_fingerprint_row({
            "video_id": vid,
            "result": "success",
            "reason": "captured",
            "duration_sec": 1.0,
            "timestamp": ts,
            "cookies_source": "local",
        })
        audit.append_transcript_row({
            "video_id": vid,
            "result": "skip",
            "reason": "skip_existing",
            "source": "",
            "timestamp": ts,
            "cookies_source": "",
        })

    # ── Stage 3: analyze content-reuse --mode M-nC2 --professor TestProf ─────
    map_professor(
        professor_id=_PROFESSOR,
        display_name="Test Professor",
        channel_alias=_CHANNEL,
        author_marker="__channel_owner__",
        db_path=db_path,
        registered_by="test",
    )

    db_obj2 = ContentDB(db_path)
    try:
        analysis = run_nc2_analysis(
            professor=_PROFESSOR,
            channel_alias=_CHANNEL,
            db=db_obj2,
            matching_mode="M-nC2",
            layer_a_min_seconds=0.0,
        )
    finally:
        db_obj2.close()

    # C(9,2) = 36 pairs
    assert analysis.total_pairs_generated == 36, (
        f"Expected 36 nC2 pairs, got {analysis.total_pairs_generated}"
    )

    # Audit for analyze stage
    audit.append_row("analyze", {
        "professor": _PROFESSOR,
        "channel": _CHANNEL,
        "result": "success",
        "reason": "analyzed",
        "pair_count": analysis.pairs_analyzed,
        "timestamp": ts,
    })

    # ── Stage 4: report content-reuse --format html ───────────────────────────
    # Pass channel_dir as output_dir so AuditWriter writes to channel_dir/01_collect/
    db_obj3 = ContentDB(db_path)
    try:
        report = render_professor_nc2_report(
            professor=_PROFESSOR,
            channel_alias=_CHANNEL,
            db=db_obj3,
            output_dir=channel_dir,
            output_format="html",
        )
    finally:
        db_obj3.close()

    # ── Assertions ────────────────────────────────────────────────────────────

    # HTML report exists
    assert report.html_path is not None, "HTML report path must be set"
    assert report.html_path.exists(), f"HTML report not generated: {report.html_path}"
    assert report.pair_count == 36, f"Expected 36 pairs in report, got {report.pair_count}"

    # SQLite tables fully populated
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM channel_metadata").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM video_metadata").fetchone()[0] == 9
        assert conn.execute("SELECT COUNT(*) FROM audio_fingerprint").fetchone()[0] == 9, (
            "audio_fingerprint must have 9 rows"
        )
        cr_count = conn.execute(
            "SELECT COUNT(*) FROM comparison_results WHERE professor = ?",
            (_PROFESSOR,),
        ).fetchone()[0]
        assert cr_count == 36, f"Expected 36 comparison_results rows, got {cr_count}"

    # Audit CSV files present (takeout_ingest + fingerprint + transcripts + analyze + report)
    collect_dir = work_root / _CHANNEL / "01_collect"
    for stage in ("takeout_ingest", "fingerprint", "transcripts", "analyze", "report"):
        audit_csv = collect_dir / f"{stage}_audit.csv"
        assert audit_csv.exists(), f"Missing audit CSV: {audit_csv}"


@pytest.mark.slow
def test_us1_pipeline_report_html_no_forbidden_tokens(tmp_path: Path) -> None:
    """SC-007: rendered US1 pipeline report HTML must not contain definitive-verdict tokens."""
    from tube_scout.reporting.professor_nc2 import (
        render_professor_nc2_report,
    )
    from tube_scout.services.nc2_matcher import run_nc2_analysis
    from tube_scout.services.professor_resolver import map_professor
    from tube_scout.services.takeout_ingest import ingest_takeout
    from tube_scout.storage.content_db import ContentDB

    work_root = tmp_path / "data"
    work_root.mkdir()
    db_path = work_root / "content_reuse.db"
    output_dir = tmp_path / "reports"

    with (
        patch("tube_scout.services.takeout_ingest._load_alias_registry", return_value=_make_registry()),
        patch("subprocess.run", side_effect=_fake_ffprobe),
    ):
        ingest_takeout(
            takeout_dir=FIXTURE_TAKEOUT,
            channel_alias=_CHANNEL,
            db_path=db_path,
            work_root=work_root,
        )

    map_professor(
        professor_id=_PROFESSOR,
        display_name="Test Professor",
        channel_alias=_CHANNEL,
        author_marker="__channel_owner__",
        db_path=db_path,
        registered_by="test",
    )

    db_obj = ContentDB(db_path)
    try:
        run_nc2_analysis(
            professor=_PROFESSOR,
            channel_alias=_CHANNEL,
            db=db_obj,
            matching_mode="M-nC2",
            layer_a_min_seconds=0.0,
        )
    finally:
        db_obj.close()

    db_obj2 = ContentDB(db_path)
    try:
        report = render_professor_nc2_report(
            professor=_PROFESSOR,
            channel_alias=_CHANNEL,
            db=db_obj2,
            output_dir=output_dir,
            output_format="html",
        )
    finally:
        db_obj2.close()

    html = report.html_path.read_text(encoding="utf-8")
    for token in ["재활용 확정", "위반", "표절", "복제"]:
        assert token not in html, f"SC-007: forbidden token '{token}' in pipeline report HTML"
