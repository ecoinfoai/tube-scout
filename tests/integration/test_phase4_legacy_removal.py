"""Phase 5 (US3) legacy-removal regression — spec 013 T087.

This test guards the yt-dlp surface removal. It is intentionally RED
*before* T089-T094 deletions (yt-dlp modules still resolvable, `--source
ytdlp` still a documented value), and turns GREEN once Phase 5 finishes.

Assertions (per tasks.md T087):
    (a) ``AuditWriter`` import path stable.
    (b) ``append_row("transcripts", ...)`` and ``append_row("fingerprint",
        ...)`` continue to work for spec 012-style records — frozen
        fieldnames must not regress.
    (c) All 8 spec 013 stage fieldnames intact and exactly the documented
        column order.
    (d) ``collect transcripts --source`` no longer advertises ``ytdlp``
        (help text + accepted values).
    (e) ``tube_scout.cli.collect._dispatch_ytdlp_transcripts`` is not
        importable as a module-level symbol.
    (f) The yt-dlp surface modules (``services/ytdlp_adapter.py``,
        ``services/ytdlp_errors.py``, ``services/srv3_parser.py``) are
        not importable.

References: spec.md FR-046/FR-047, services/audit_writer.py:15-61.
"""

from __future__ import annotations

import importlib
import inspect
from pathlib import Path
from typing import Any

import pytest
import typer

# ─── (a) AuditWriter import surface ───────────────────────────────────────────


def test_a_audit_writer_import_works() -> None:
    """AuditWriter is reachable via its canonical service path."""
    from tube_scout.services.audit_writer import AuditWriter

    assert AuditWriter is not None
    assert inspect.isclass(AuditWriter)


# ─── (b) append_row for transcripts + fingerprint stages stays functional ────


def test_b_append_row_transcripts_and_fingerprint(tmp_path: Path) -> None:
    """transcripts + fingerprint stages still accept their frozen rows."""
    from tube_scout.services.audit_writer import AuditWriter

    writer = AuditWriter(project_dir=tmp_path)

    writer.append_row(
        "transcripts",
        {
            "video_id": "vid_001",
            "result": "success",
            "reason": "captured",
            "source": "api",
            "caption_source_detail": "captions_api_manual",
            "timestamp": "2026-05-14T00:00:00+09:00",
            "cookies_source": "none",
        },
    )
    writer.append_row(
        "fingerprint",
        {
            "video_id": "vid_001",
            "result": "success",
            "reason": "extracted",
            "duration_sec": 600,
            "fingerprint_input_policy": "wav_full",
            "timestamp": "2026-05-14T00:00:00+09:00",
            "cookies_source": "none",
        },
    )

    transcripts_csv = tmp_path / "01_collect" / "transcripts_audit.csv"
    fingerprint_csv = tmp_path / "01_collect" / "fingerprint_audit.csv"
    assert transcripts_csv.exists()
    assert fingerprint_csv.exists()


# ─── (c) all 8 stage frozen fieldnames intact ─────────────────────────────────


def test_c_eight_stage_frozen_fieldnames() -> None:
    """STAGE_FIELDNAMES has exactly 8 keys with frozen column orders."""
    from tube_scout.services.audit_writer import (
        ANALYZE_FIELDNAMES,
        AUDIO_EXTRACT_FIELDNAMES,
        FINGERPRINT_FIELDNAMES,
        KB_EXPORT_FIELDNAMES,
        NORMALIZE_FIELDNAMES,
        REPORT_FIELDNAMES,
        STAGE_FIELDNAMES,
        TAKEOUT_INGEST_FIELDNAMES,
        TRANSCRIPTS_FIELDNAMES,
    )

    assert set(STAGE_FIELDNAMES.keys()) == {
        "takeout_ingest",
        "audio_extract",
        "transcripts",
        "fingerprint",
        "normalize",
        "analyze",
        "report",
        "kb_export",
    }
    assert STAGE_FIELDNAMES["takeout_ingest"] == TAKEOUT_INGEST_FIELDNAMES
    assert STAGE_FIELDNAMES["audio_extract"] == AUDIO_EXTRACT_FIELDNAMES
    assert STAGE_FIELDNAMES["transcripts"] == TRANSCRIPTS_FIELDNAMES
    assert STAGE_FIELDNAMES["fingerprint"] == FINGERPRINT_FIELDNAMES
    assert STAGE_FIELDNAMES["normalize"] == NORMALIZE_FIELDNAMES
    assert STAGE_FIELDNAMES["analyze"] == ANALYZE_FIELDNAMES
    assert STAGE_FIELDNAMES["report"] == REPORT_FIELDNAMES
    assert STAGE_FIELDNAMES["kb_export"] == KB_EXPORT_FIELDNAMES

    assert TRANSCRIPTS_FIELDNAMES == (
        "video_id", "result", "reason",
        "source", "caption_source_detail", "timestamp", "cookies_source",
    )
    assert FINGERPRINT_FIELDNAMES == (
        "video_id", "result", "reason",
        "duration_sec", "fingerprint_input_policy", "timestamp",
        "cookies_source",
    )
    assert TAKEOUT_INGEST_FIELDNAMES == (
        "video_id", "result", "reason",
        "mp4_filename", "match_confidence", "score", "timestamp",
    )
    assert AUDIO_EXTRACT_FIELDNAMES == (
        "video_id", "result", "reason",
        "input_kind", "output_path", "wav_size_bytes", "elapsed_s",
        "timestamp",
    )
    assert NORMALIZE_FIELDNAMES == (
        "video_id", "result", "reason",
        "input_source", "normalizer_version", "timestamp",
    )
    assert ANALYZE_FIELDNAMES == (
        "pair_id", "source_video_id", "target_video_id",
        "result", "reason", "matching_mode", "elapsed_s", "timestamp",
    )
    assert REPORT_FIELDNAMES == (
        "professor", "channel", "result", "reason",
        "format", "output_path", "pair_count", "appendix_count", "timestamp",
    )
    assert KB_EXPORT_FIELDNAMES == (
        "video_id", "result", "reason",
        "format", "output_path", "byte_count", "timestamp",
    )


# ─── (d) collect transcripts --source no longer advertises ytdlp ─────────────


def test_d_collect_transcripts_source_option_drops_ytdlp() -> None:
    """The --source option help text must not list 'ytdlp' anymore."""
    from tube_scout.cli.collect import collect_transcripts_command

    sig = inspect.signature(collect_transcripts_command)
    param = sig.parameters["source"]
    option: Any = param.default
    assert isinstance(option, typer.models.OptionInfo)
    help_text = option.help or ""
    assert "ytdlp" not in help_text.lower(), (
        f"--source help still mentions ytdlp: {help_text!r}"
    )


# ─── (e) _dispatch_ytdlp_transcripts no longer importable ─────────────────────


def test_e_dispatch_ytdlp_transcripts_not_importable() -> None:
    """The dispatcher helper for ytdlp must be gone from the CLI module."""
    import tube_scout.cli.collect as collect_module

    assert not hasattr(collect_module, "_dispatch_ytdlp_transcripts"), (
        "tube_scout.cli.collect._dispatch_ytdlp_transcripts must be removed"
    )


# ─── (f) ytdlp surface modules not importable ─────────────────────────────────


@pytest.mark.parametrize(
    "modname",
    [
        "tube_scout.services.ytdlp_adapter",
        "tube_scout.services.ytdlp_errors",
        "tube_scout.services.srv3_parser",
    ],
)
def test_f_ytdlp_surface_modules_not_importable(modname: str) -> None:
    """Each yt-dlp surface module must raise ModuleNotFoundError on import."""
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module(modname)
