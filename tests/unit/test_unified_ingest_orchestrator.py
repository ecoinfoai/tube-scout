"""T011 RED — unit tests for services/unified_ingest.py::ingest_unified (spec 017 US1).

Tests verify call ordering and SC-005 (audio decode once per mp4).
All tests fail at RED stage: services.unified_ingest does not yet exist.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

_AUDIO_FP_SQL = """
CREATE TABLE IF NOT EXISTS audio_fingerprint (
    video_id     TEXT PRIMARY KEY,
    fingerprint  BLOB NOT NULL,
    duration     REAL NOT NULL,
    extracted_at TEXT NOT NULL,
    source       TEXT NOT NULL DEFAULT 'fpcalc:1.6.0'
);
"""


def _make_test_db(path: Path) -> Path:
    """Create a SQLite DB with audio_fingerprint table for idempotency guard."""
    with sqlite3.connect(str(path)) as conn:
        conn.executescript(_AUDIO_FP_SQL)
    return path


def _make_ingest_result(
    channel_alias: str = "nursing",
    mp4_present_count: int = 2,
):  # returns IngestResult (local import avoids top-level dependency)
    """Build a minimal IngestResult mock representing spec 016 output."""
    from tube_scout.services.takeout_ingest import IngestResult
    dummy_map = {
        f"/fake/path/video_{i}.mp4": f"vid{i:04d}"
        for i in range(mp4_present_count)
    }
    return IngestResult(
        channel_id="UCtest001",
        channel_alias=channel_alias,
        total_videos=10,
        new_videos=10,
        high_confidence_mappings=mp4_present_count,
        medium_confidence_mappings=0,
        ambiguous_mappings=0,
        unmapped_filenames=0,
        ignored_csv_count=0,
        dry_run=False,
        mp4_present_count=mp4_present_count,
        mp4_absent_count=10 - mp4_present_count,
        elapsed_seconds=0.0,
        mp4_video_id_map=dummy_map,
    )


def _make_stage_results():
    """Build minimal TranscriptStageResult and FingerprintStageResult for mocking."""
    from tube_scout.models.content import FingerprintStageResult, TranscriptStageResult
    tr = TranscriptStageResult(
        success_count=0, failure_count=0, skipped_no_mp4_count=0,
        failures=[], elapsed_seconds=0.0,
    )
    fr = FingerprintStageResult(
        success_count=0, failure_count=0, skipped_no_mp4_count=0,
        failures=[], elapsed_seconds=0.0,
    )
    return tr, fr


def _make_retry_manifest_delta(manifest_path: Path | None = None):
    """Build a minimal RetryManifestDelta for _update_retry_manifest mock return."""
    from tube_scout.models.content import RetryManifestDelta
    return RetryManifestDelta(
        added_count=0,
        resolved_count=0,
        remaining_count=0,
        manifest_path=manifest_path or Path("/tmp/retry_pending.json"),
    )


def _import_ingest_unified():
    from tube_scout.services.unified_ingest import ingest_unified
    return ingest_unified


def test_calls_ingest_takeout_first(tmp_path: Path) -> None:
    """ingest_unified calls services.takeout_ingest.ingest_takeout as the first step."""
    ingest_unified = _import_ingest_unified()

    with patch(
        "tube_scout.services.unified_ingest.ingest_takeout",
    ) as mock_takeout, patch(
        "tube_scout.services.unified_ingest._run_transcript_and_fingerprint",
        return_value=_make_stage_results(),
    ), patch(
        "tube_scout.services.unified_ingest._update_retry_manifest",
        return_value=_make_retry_manifest_delta(tmp_path / "work" / "nursing" / "retry_pending.json"),
    ):
        mock_takeout.return_value = _make_ingest_result()
        ingest_unified(
            takeout_dir=tmp_path,
            channel_alias="nursing",
            db_path=tmp_path / "test.db",
            work_root=tmp_path / "work",
            use_symlinks=True,
            dry_run=False,
            delete_source=False,
            audit_writer=MagicMock(),
            prompt_io=None,
        )

    mock_takeout.assert_called_once(), "ingest_takeout must be called exactly once (first step)"


def test_wav_lifecycle_called_per_mp4(tmp_path: Path) -> None:
    """WavLifecycle context is entered once per mp4-mapped video (boundary B-1)."""
    ingest_unified = _import_ingest_unified()
    mp4_count = 3
    db_path = _make_test_db(tmp_path / "test.db")

    with patch(
        "tube_scout.services.unified_ingest.ingest_takeout",
        return_value=_make_ingest_result(mp4_present_count=mp4_count),
    ), patch(
        "tube_scout.services.unified_ingest.WavLifecycle",
    ) as mock_wav_cls, patch(
        "tube_scout.services.unified_ingest._update_retry_manifest",
        return_value=_make_retry_manifest_delta(),
    ):
        mock_wav_cls.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_wav_cls.return_value.__exit__ = MagicMock(return_value=False)
        ingest_unified(
            takeout_dir=tmp_path,
            channel_alias="nursing",
            db_path=db_path,
            work_root=tmp_path / "work",
            use_symlinks=True,
            dry_run=False,
            delete_source=False,
            audit_writer=MagicMock(),
            prompt_io=None,
        )

    assert mock_wav_cls.call_count == mp4_count, (
        f"Expected WavLifecycle called {mp4_count} times, got {mock_wav_cls.call_count}"
    )


def test_asr_invoked_with_wav_path(tmp_path: Path) -> None:
    """transcribe_audio is called with a wav_path argument for each mp4 video (boundary B-2)."""
    ingest_unified = _import_ingest_unified()
    db_path = _make_test_db(tmp_path / "test.db")

    fake_wav = tmp_path / "audio.wav"
    fake_wav.touch()

    with patch(
        "tube_scout.services.unified_ingest.ingest_takeout",
        return_value=_make_ingest_result(mp4_present_count=1),
    ), patch(
        "tube_scout.services.unified_ingest.WavLifecycle",
    ) as mock_wav_cls, patch(
        "tube_scout.services.unified_ingest.extract_wav_16k_mono",
    ), patch(
        "tube_scout.services.unified_ingest.transcribe_audio",
    ) as mock_asr, patch(
        "tube_scout.services.unified_ingest._update_retry_manifest",
        return_value=_make_retry_manifest_delta(),
    ):
        mock_wav_cls.return_value.__enter__ = MagicMock(return_value=fake_wav)
        mock_wav_cls.return_value.__exit__ = MagicMock(return_value=False)
        mock_asr.return_value = MagicMock()
        ingest_unified(
            takeout_dir=tmp_path,
            channel_alias="nursing",
            db_path=db_path,
            work_root=tmp_path / "work",
            use_symlinks=True,
            dry_run=False,
            delete_source=False,
            audit_writer=MagicMock(),
            prompt_io=None,
        )

    mock_asr.assert_called_once()
    call_kwargs = mock_asr.call_args
    assert call_kwargs is not None, "transcribe_audio was not called"
    # wav_path must be passed (positional or keyword)
    args, kwargs = call_kwargs
    wav_arg = args[0] if args else kwargs.get("wav_path")
    assert wav_arg == fake_wav, (
        f"transcribe_audio must receive wav_path={fake_wav}, got {wav_arg}"
    )


def test_fingerprint_invoked_with_audio_path(tmp_path: Path) -> None:
    """extract_chromaprint_fingerprint is called with audio_path for each mp4 (boundary B-3)."""
    ingest_unified = _import_ingest_unified()
    db_path = _make_test_db(tmp_path / "test.db")

    fake_wav = tmp_path / "audio.wav"
    fake_wav.touch()

    with patch(
        "tube_scout.services.unified_ingest.ingest_takeout",
        return_value=_make_ingest_result(mp4_present_count=1),
    ), patch(
        "tube_scout.services.unified_ingest.WavLifecycle",
    ) as mock_wav_cls, patch(
        "tube_scout.services.unified_ingest.extract_wav_16k_mono",
    ), patch(
        "tube_scout.services.unified_ingest.extract_chromaprint_fingerprint",
    ) as mock_fp, patch(
        "tube_scout.services.unified_ingest._update_retry_manifest",
        return_value=_make_retry_manifest_delta(),
    ):
        mock_wav_cls.return_value.__enter__ = MagicMock(return_value=fake_wav)
        mock_wav_cls.return_value.__exit__ = MagicMock(return_value=False)
        mock_fp.return_value = MagicMock()
        ingest_unified(
            takeout_dir=tmp_path,
            channel_alias="nursing",
            db_path=db_path,
            work_root=tmp_path / "work",
            use_symlinks=True,
            dry_run=False,
            delete_source=False,
            audit_writer=MagicMock(),
            prompt_io=None,
        )

    mock_fp.assert_called_once()
    args, kwargs = mock_fp.call_args
    audio_arg = args[0] if args else kwargs.get("audio_path")
    assert audio_arg == fake_wav, (
        f"extract_chromaprint_fingerprint must receive audio_path={fake_wav}, got {audio_arg}"
    )


def test_summary_contains_ingest_result(tmp_path: Path) -> None:
    """Returned UnifiedIngestSummary.ingest_result is the IngestResult from ingest_takeout (B-7)."""
    ingest_unified = _import_ingest_unified()
    from tube_scout.services.takeout_ingest import IngestResult

    expected_ingest = _make_ingest_result()

    with patch(
        "tube_scout.services.unified_ingest.ingest_takeout",
        return_value=expected_ingest,
    ), patch(
        "tube_scout.services.unified_ingest._run_transcript_and_fingerprint",
        return_value=_make_stage_results(),
    ), patch(
        "tube_scout.services.unified_ingest._update_retry_manifest",
        return_value=_make_retry_manifest_delta(),
    ):
        summary = ingest_unified(
            takeout_dir=tmp_path,
            channel_alias="nursing",
            db_path=tmp_path / "test.db",
            work_root=tmp_path / "work",
            use_symlinks=True,
            dry_run=False,
            delete_source=False,
            audit_writer=MagicMock(),
            prompt_io=None,
        )

    assert isinstance(summary.ingest_result, IngestResult), (
        "summary.ingest_result must be IngestResult (boundary B-7)"
    )
    assert summary.ingest_result is expected_ingest, (
        "summary.ingest_result must be the exact object returned by ingest_takeout"
    )


def test_sc_005_audio_decode_once_per_mp4(tmp_path: Path) -> None:
    """SC-005: each mp4 is decoded to WAV exactly once, shared by ASR and fingerprint stages."""
    ingest_unified = _import_ingest_unified()
    mp4_count = 9
    db_path = _make_test_db(tmp_path / "test.db")

    wav_enter_count = 0

    class _CountingWavLifecycle:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            nonlocal wav_enter_count
            wav_enter_count += 1
            return tmp_path / f"audio_{wav_enter_count}.wav"

        def __exit__(self, *args):
            return False

    with patch(
        "tube_scout.services.unified_ingest.ingest_takeout",
        return_value=_make_ingest_result(mp4_present_count=mp4_count),
    ), patch(
        "tube_scout.services.unified_ingest.WavLifecycle",
        _CountingWavLifecycle,
    ), patch(
        "tube_scout.services.unified_ingest.transcribe_audio",
        return_value=MagicMock(),
    ), patch(
        "tube_scout.services.unified_ingest.extract_chromaprint_fingerprint",
        return_value=MagicMock(),
    ), patch(
        "tube_scout.services.unified_ingest._update_retry_manifest",
        return_value=_make_retry_manifest_delta(),
    ):
        ingest_unified(
            takeout_dir=tmp_path,
            channel_alias="nursing",
            db_path=db_path,
            work_root=tmp_path / "work",
            use_symlinks=True,
            dry_run=False,
            delete_source=False,
            audit_writer=MagicMock(),
            prompt_io=None,
        )

    assert wav_enter_count == mp4_count, (
        f"SC-005: WAV decode must happen exactly once per mp4 ({mp4_count}), "
        f"got {wav_enter_count}"
    )


def test_mp4_absent_skips_asr_and_fingerprint(tmp_path: Path) -> None:
    """Videos without mp4 are skipped for ASR and fingerprint with audit no_mp4_in_archive (FR-008)."""
    ingest_unified = _import_ingest_unified()

    # 0 mp4 present → all videos are mp4-absent
    with patch(
        "tube_scout.services.unified_ingest.ingest_takeout",
        return_value=_make_ingest_result(mp4_present_count=0),
    ), patch(
        "tube_scout.services.unified_ingest.WavLifecycle",
    ) as mock_wav_cls, patch(
        "tube_scout.services.unified_ingest.transcribe_audio",
    ) as mock_asr, patch(
        "tube_scout.services.unified_ingest.extract_chromaprint_fingerprint",
    ) as mock_fp, patch(
        "tube_scout.services.unified_ingest._update_retry_manifest",
        return_value=_make_retry_manifest_delta(),
    ):
        summary = ingest_unified(
            takeout_dir=tmp_path,
            channel_alias="nursing",
            db_path=tmp_path / "test.db",
            work_root=tmp_path / "work",
            use_symlinks=True,
            dry_run=False,
            delete_source=False,
            audit_writer=MagicMock(),
            prompt_io=None,
        )

    assert mock_wav_cls.call_count == 0, (
        "WavLifecycle must not be entered for mp4-absent videos (FR-008, boundary B-2)"
    )
    assert mock_asr.call_count == 0, (
        "transcribe_audio must not be called for mp4-absent videos"
    )
    assert mock_fp.call_count == 0, (
        "extract_chromaprint_fingerprint must not be called for mp4-absent videos"
    )
    assert summary.transcript_result.skipped_no_mp4_count == 10, (
        "All 10 mp4-absent videos must appear in skipped_no_mp4_count"
    )
