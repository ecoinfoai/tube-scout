"""Professor nC2 reuse report renderer (spec 013 FR-035~FR-039)."""

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from jinja2 import Environment, FileSystemLoader
from pydantic import BaseModel

from tube_scout.storage.content_db import ContentDB

ReportFormat = Literal["pdf", "html", "both"]
SortMetric = Literal[
    "i2-cosine",
    "i6-longest-contiguous",
    "i7-distribution-dispersion",
    "i8-position-diversity",
    "audio-fp-hamming",
]

_SORT_COLUMN: dict[str, str] = {
    "i2-cosine": "i2_cosine_similarity",
    "i6-longest-contiguous": "i6_longest_contiguous_seconds",
    "i7-distribution-dispersion": "i7_distribution_dispersion",
    "i8-position-diversity": "i8_position_diversity",
    "audio-fp-hamming": "audio_fp_hamming",
}


class AppendixThresholds(BaseModel):
    """Per-metric appendix thresholds (C-3 Phase 3 운영, deferred aggregate score)."""

    i2_cosine: float | None = None
    i6_longest_contiguous: float | None = None
    i7_distribution_dispersion: float | None = None
    i8_position_diversity: float | None = None
    audio_fp_hamming: int | None = None


class ReportResult(BaseModel):
    """Output of render_professor_nc2_report."""

    professor: str
    channel_alias: str
    html_path: Path | None
    pdf_path: Path | None
    pair_count: int
    top_k_count: int
    appendix_count: int
    pattern_distribution: dict[str, int]
    generated_at: datetime


def passes_appendix(pair: Any, t: AppendixThresholds) -> bool:
    """Return True if pair exceeds any configured appendix threshold (OR semantics).

    When all thresholds are None (Phase 3 30-day default), every pair is admitted.

    Args:
        pair: Object with i2_cosine_similarity, i6_longest_contiguous_seconds,
              i7_distribution_dispersion, i8_position_diversity, audio_fp_hamming.
        t: AppendixThresholds with per-metric thresholds (None = disabled).

    Returns:
        True if pair should appear in the appendix.
    """
    if (
        t.i2_cosine is None
        and t.i6_longest_contiguous is None
        and t.i7_distribution_dispersion is None
        and t.i8_position_diversity is None
        and t.audio_fp_hamming is None
    ):
        return True
    if t.i2_cosine is not None and pair.i2_cosine_similarity >= t.i2_cosine:
        return True
    if (
        t.i6_longest_contiguous is not None
        and pair.i6_longest_contiguous_seconds >= t.i6_longest_contiguous
    ):
        return True
    if (
        t.i7_distribution_dispersion is not None
        and pair.i7_distribution_dispersion >= t.i7_distribution_dispersion
    ):
        return True
    if t.i8_position_diversity is not None and pair.i8_position_diversity >= t.i8_position_diversity:
        return True
    if (
        t.audio_fp_hamming is not None
        and pair.audio_fp_hamming is not None
        and pair.audio_fp_hamming >= t.audio_fp_hamming
    ):
        return True
    return False


def _render_pdf(html_str: str, pdf_path: Path) -> None:
    """Render HTML string to PDF via weasyprint (lazy import).

    Args:
        html_str: Full HTML content.
        pdf_path: Output path for the PDF file.

    Raises:
        ImportError: If weasyprint is not installed.
    """
    try:
        from weasyprint import HTML
    except ImportError as e:
        raise ImportError(
            "weasyprint is not installed. Install with: uv sync --extra pdf"
        ) from e
    HTML(string=html_str).write_pdf(pdf_path)


def _query_pairs(
    conn: sqlite3.Connection,
    professor: str,
    matching_mode: str,
    sort_col: str,
    top_k: int,
) -> list[sqlite3.Row]:
    """Query top_k comparison_results rows with video_metadata and audio_fingerprint JOIN.

    Args:
        conn: SQLite connection.
        professor: Professor identifier to filter.
        matching_mode: Matching mode ('M-default' or 'M-nC2').
        sort_col: Column name to sort by (descending).
        top_k: Maximum rows to return.

    Returns:
        List of sqlite3.Row results.
    """
    query = f"""
        SELECT
            cr.*,
            vm_src.title AS source_title,
            vm_src.duration_seconds AS src_duration_seconds,
            vm_src.privacy_status AS src_privacy_status,
            vm_src.created_at AS src_created_at,
            vm_tgt.title AS target_title,
            vm_tgt.duration_seconds AS tgt_duration_seconds,
            vm_tgt.privacy_status AS tgt_privacy_status,
            vm_tgt.created_at AS tgt_created_at
        FROM comparison_results cr
        LEFT JOIN video_metadata vm_src ON cr.source_video_id = vm_src.video_id
        LEFT JOIN video_metadata vm_tgt ON cr.target_video_id = vm_tgt.video_id
        WHERE cr.professor = ?
          AND cr.matching_mode = ?
        ORDER BY cr.{sort_col} DESC NULLS LAST
        LIMIT ?
    """
    return conn.execute(query, (professor, matching_mode, top_k)).fetchall()


def _query_all_pairs(
    conn: sqlite3.Connection,
    professor: str,
    matching_mode: str,
) -> list[sqlite3.Row]:
    """Query all comparison_results rows for a professor.

    Args:
        conn: SQLite connection.
        professor: Professor identifier.
        matching_mode: Matching mode.

    Returns:
        All matching rows.
    """
    return conn.execute(
        "SELECT * FROM comparison_results WHERE professor = ? AND matching_mode = ?",
        (professor, matching_mode),
    ).fetchall()


def _query_video_count(conn: sqlite3.Connection, professor: str) -> int:
    """Count distinct videos referenced by a professor's comparison pairs.

    Args:
        conn: SQLite connection.
        professor: Professor identifier.

    Returns:
        Count of distinct video IDs.
    """
    row = conn.execute(
        """
        SELECT COUNT(DISTINCT vid) FROM (
            SELECT source_video_id AS vid FROM comparison_results WHERE professor = ?
            UNION
            SELECT target_video_id AS vid FROM comparison_results WHERE professor = ?
        )
        """,
        (professor, professor),
    ).fetchone()
    return row[0] if row else 0


def _build_pattern_distribution(rows: list[sqlite3.Row]) -> dict[str, int]:
    dist: dict[str, int] = {}
    for row in rows:
        pattern = row["reuse_pattern"] or "UNKNOWN"
        dist[pattern] = dist.get(pattern, 0) + 1
    return dist


def _get_period(conn: sqlite3.Connection, professor: str) -> tuple[str | None, str | None]:
    row = conn.execute(
        """
        SELECT MIN(vm.created_at), MAX(vm.created_at)
        FROM comparison_results cr
        JOIN video_metadata vm ON cr.source_video_id = vm.video_id
        WHERE cr.professor = ?
        """,
        (professor,),
    ).fetchone()
    if row:
        return row[0], row[1]
    return None, None


def render_professor_nc2_report(
    professor: str,
    channel_alias: str,
    db: ContentDB,
    output_dir: Path,
    *,
    matching_mode: Literal["M-default", "M-nC2"] = "M-nC2",
    top_k: int = 50,
    sort_by: SortMetric = "i2-cosine",
    appendix_thresholds: AppendixThresholds = AppendixThresholds(),
    output_format: ReportFormat = "both",
) -> ReportResult:
    """Render per-professor M-nC2 reuse report (PDF + HTML).

    Args:
        professor: Professor identifier.
        channel_alias: Human-readable channel alias.
        db: Open ContentDB connection.
        output_dir: Directory for output files.
        matching_mode: Matching mode label to filter.
        top_k: Maximum suspect pairs in main list.
        sort_by: Metric axis for descending sort.
        appendix_thresholds: Per-metric OR thresholds for appendix filtering.
        output_format: Output format ('html', 'pdf', or 'both').

    Returns:
        ReportResult with output paths and summary counts.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    conn = db._conn
    sort_col = _SORT_COLUMN[sort_by]

    all_rows = _query_all_pairs(conn, professor, matching_mode)
    top_rows = _query_pairs(conn, professor, matching_mode, sort_col, top_k)
    video_count = _query_video_count(conn, professor)
    period_start, period_end = _get_period(conn, professor)

    pattern_distribution = _build_pattern_distribution(all_rows)

    class _RowProxy:
        """Thin wrapper to expose sqlite3.Row fields as attribute access."""

        def __init__(self, row: sqlite3.Row) -> None:
            self._row = row

        def __getattr__(self, name: str) -> Any:
            try:
                return self._row[name]
            except IndexError:
                return None

    top_pairs = [_RowProxy(r) for r in top_rows]
    appendix_pairs = [p for p in top_pairs if passes_appendix(p, appendix_thresholds)]

    generated_at = datetime.now(tz=UTC)

    templates_dir = Path(__file__).parent / "templates"
    env = Environment(
        loader=FileSystemLoader(str(templates_dir)),
        autoescape=False,
    )
    template = env.get_template("professor_nC2_report.html")

    ctx = {
        "professor": professor,
        "channel_alias": channel_alias,
        "period_start": period_start,
        "period_end": period_end,
        "video_count": video_count,
        "pair_count": len(all_rows),
        "matching_mode": matching_mode,
        "generated_at": generated_at.strftime("%Y-%m-%d %H:%M:%S UTC"),
        "top_k": top_k,
        "top_k_count": len(top_pairs),
        "appendix_count": len(appendix_pairs),
        "top_pairs": top_pairs,
        "appendix_pairs": appendix_pairs,
        "pattern_distribution": pattern_distribution,
        "metric_charts": {},
        "category_chart_png": None,
        "year_trend_chart_png": None,
        "layer_stats": None,
    }

    html_str = template.render(**ctx)

    html_path: Path | None = None
    pdf_path: Path | None = None

    safe_prof = professor.replace("/", "_").replace("\\", "_")
    if output_format in ("html", "both"):
        html_path = output_dir / f"{safe_prof}_nC2_report.html"
        html_path.write_text(html_str, encoding="utf-8")

    if output_format in ("pdf", "both"):
        pdf_path = output_dir / f"{safe_prof}_nC2_report.pdf"
        _render_pdf(html_str, pdf_path)

    # Audit row
    try:
        from tube_scout.services.audit_writer import AuditWriter
        writer = AuditWriter(output_dir)
        writer.append_row("report", {
            "professor": professor,
            "channel": channel_alias,
            "result": "success",
            "reason": "rendered",
            "format": output_format,
            "output_path": str(html_path or pdf_path or output_dir),
            "pair_count": len(all_rows),
            "appendix_count": len(appendix_pairs),
            "timestamp": generated_at.isoformat(),
        })
    except Exception:
        pass

    return ReportResult(
        professor=professor,
        channel_alias=channel_alias,
        html_path=html_path,
        pdf_path=pdf_path,
        pair_count=len(all_rows),
        top_k_count=len(top_pairs),
        appendix_count=len(appendix_pairs),
        pattern_distribution=pattern_distribution,
        generated_at=generated_at,
    )
