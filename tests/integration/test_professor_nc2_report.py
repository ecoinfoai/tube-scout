"""T078 RED — full integration test for professor_nc2_report (spec 013).

Mini-nC2 9-video fixture → 36 pairs → render_professor_nc2_report.
"""
import itertools
from pathlib import Path

import pytest

_PROFESSOR = "test-prof-T078"
_CHANNEL = "test-channel-T078"
_VIDEO_IDS = [f"REPT078{i:03d}" for i in range(1, 10)]  # 9 videos → C(9,2)=36 pairs


def _setup_db(db_path: Path) -> None:
    from tube_scout.storage.content_db import (
        ContentDB,
        _ensure_v4,
        migrate_to_v2,
        migrate_to_v3,
    )

    ContentDB(db_path).close()
    migrate_to_v2(db_path)
    migrate_to_v3(db_path)
    _ensure_v4(db_path)

    import sqlite3
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    # Insert video_metadata for 9 videos
    for vid in _VIDEO_IDS:
        conn.execute(
            """
            INSERT OR IGNORE INTO video_metadata
                (video_id, channel_id, title, duration_seconds, category, privacy_status,
                 created_at, source, ingested_at)
            VALUES (?, 'chan-T078', ?, 1800.0, 'Education', 'unlisted',
                    '2026-01-01T09:00:00Z', 'takeout', '2026-05-01T00:00:00Z')
            """,
            (vid, f"강의 {vid}"),
        )

    # Insert 36 comparison pairs C(9,2) with M-nC2
    for i, (src, tgt) in enumerate(itertools.combinations(_VIDEO_IDS, 2)):
        score = 0.50 + (i / 100)
        pattern = "WHOLE_SAME_WEEK" if i % 3 == 0 else ("PARTIAL_COPY" if i % 3 == 1 else "SCATTERED_DIFF_WEEK")
        conn.execute(
            """
            INSERT OR IGNORE INTO comparison_results
                (source_video_id, target_video_id, professor, course, week, session,
                 year_from, year_to, i2_cosine_similarity, matching_mode, reuse_pattern,
                 audio_fp_hamming, source_type_pair, created_at)
            VALUES (?, ?, ?, 'CS101', 1, 1, 2025, 2026, ?, 'M-nC2', ?, ?, ?, datetime('now'))
            """,
            (src, tgt, _PROFESSOR, score, pattern, 10 + i, "asr-asr"),
        )
    conn.commit()
    conn.close()


@pytest.mark.slow
def test_nc2_report_html_generated(tmp_path: Path) -> None:
    """36 pairs → render HTML → file exists and pair_count == 36."""
    from tube_scout.reporting.professor_nc2 import (
        render_professor_nc2_report,
    )
    from tube_scout.storage.content_db import ContentDB

    db_path = tmp_path / "reuse.db"
    _setup_db(db_path)

    db = ContentDB(db_path)
    try:
        result = render_professor_nc2_report(
            professor=_PROFESSOR,
            channel_alias=_CHANNEL,
            db=db,
            output_dir=tmp_path,
            output_format="html",
        )
    finally:
        db.close()

    assert result.html_path is not None
    assert result.html_path.exists(), f"HTML report not created: {result.html_path}"
    assert result.pair_count == 36, f"Expected 36 pairs, got {result.pair_count}"
    assert result.pattern_distribution, "pattern_distribution must be populated"
    # all pairs admitted to appendix (no thresholds set)
    assert result.appendix_count == 36


@pytest.mark.slow
def test_nc2_report_appendix_threshold_filters_pairs(tmp_path: Path) -> None:
    """Setting i2_cosine threshold → only pairs above threshold enter appendix."""
    from tube_scout.reporting.professor_nc2 import (
        AppendixThresholds,
        render_professor_nc2_report,
    )
    from tube_scout.storage.content_db import ContentDB

    db_path = tmp_path / "reuse.db"
    _setup_db(db_path)

    # scores range from 0.50 to 0.85, threshold at 0.80 → only top few admitted
    db = ContentDB(db_path)
    try:
        result = render_professor_nc2_report(
            professor=_PROFESSOR,
            channel_alias=_CHANNEL,
            db=db,
            output_dir=tmp_path,
            output_format="html",
            appendix_thresholds=AppendixThresholds(i2_cosine=0.80),
        )
    finally:
        db.close()

    assert result.appendix_count < 36, (
        f"Threshold 0.80 should filter pairs; appendix_count={result.appendix_count}"
    )
    assert result.appendix_count > 0, "Some pairs should exceed 0.80 threshold"


@pytest.mark.slow
def test_nc2_report_html_no_forbidden_tokens(tmp_path: Path) -> None:
    """SC-007 regression in rendered HTML: no definitive-verdict tokens."""
    from tube_scout.reporting.professor_nc2 import (
        render_professor_nc2_report,
    )
    from tube_scout.storage.content_db import ContentDB

    db_path = tmp_path / "reuse.db"
    _setup_db(db_path)

    db = ContentDB(db_path)
    try:
        result = render_professor_nc2_report(
            professor=_PROFESSOR,
            channel_alias=_CHANNEL,
            db=db,
            output_dir=tmp_path,
            output_format="html",
        )
    finally:
        db.close()

    assert result.html_path is not None
    html_content = result.html_path.read_text(encoding="utf-8")
    for token in ["재활용 확정", "위반", "표절", "복제"]:
        assert token not in html_content, f"SC-007: forbidden token '{token}' in rendered HTML"


@pytest.mark.slow
def test_nc2_report_audio_fp_columns_in_top_pairs(tmp_path: Path) -> None:
    """G1/G2: audio_fp_hamming and source_type_pair are present in top_pairs data."""
    from tube_scout.reporting.professor_nc2 import (
        render_professor_nc2_report,
    )
    from tube_scout.storage.content_db import ContentDB

    db_path = tmp_path / "reuse.db"
    _setup_db(db_path)

    db = ContentDB(db_path)
    try:
        result = render_professor_nc2_report(
            professor=_PROFESSOR,
            channel_alias=_CHANNEL,
            db=db,
            output_dir=tmp_path,
            output_format="html",
        )
    finally:
        db.close()

    # HTML contains audio_fp_hamming values (10..45) and source_type_pair 'asr-asr'
    html_content = result.html_path.read_text(encoding="utf-8")
    assert "asr-asr" in html_content, "source_type_pair 'asr-asr' must appear in report"
    # At least some hamming values should appear
    assert any(str(v) in html_content for v in range(10, 50)), (
        "audio_fp_hamming values must appear in rendered HTML"
    )


@pytest.mark.slow
def test_nc2_report_pdf_generated_if_weasyprint_available(tmp_path: Path) -> None:
    """PDF output created when weasyprint extra is installed."""
    pytest.importorskip("weasyprint", reason="weasyprint not installed — skip PDF test")

    from tube_scout.reporting.professor_nc2 import (
        render_professor_nc2_report,
    )
    from tube_scout.storage.content_db import ContentDB

    db_path = tmp_path / "reuse.db"
    _setup_db(db_path)

    db = ContentDB(db_path)
    try:
        result = render_professor_nc2_report(
            professor=_PROFESSOR,
            channel_alias=_CHANNEL,
            db=db,
            output_dir=tmp_path,
            output_format="pdf",
        )
    finally:
        db.close()

    assert result.pdf_path is not None
    assert result.pdf_path.exists(), f"PDF report not created: {result.pdf_path}"
