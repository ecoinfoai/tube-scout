"""End-to-end integration test for content reuse detection pipeline.

Tests the full flow: fingerprint → compare → quality → review → report.
"""

import json
from pathlib import Path

import pytest

from tube_scout.reporting.content_report import ContentReportGenerator
from tube_scout.services.content_comparator import (
    ContentComparator,
    match_comparison_pairs,
)
from tube_scout.services.fingerprint import FingerprintService
from tube_scout.services.quality_checker import QualityChecker
from tube_scout.storage.content_db import ContentDB


@pytest.fixture()
def project_dir(tmp_path: Path) -> Path:
    """Create a mock project directory."""
    return tmp_path / "project"


@pytest.fixture()
def db(project_dir: Path) -> ContentDB:
    """Create a content database."""
    return ContentDB(project_dir / "tube_scout.db")


class TestContentE2EPipeline:
    """Full pipeline test from fingerprint through report generation."""

    def _create_test_data(self) -> dict:
        """Create test data simulating collected captions and metadata."""
        return {
            "transcripts": {
                # 2025 videos
                "v_math_2025_w1": [
                    {"text": "오늘 수학 강의 시작하겠습니다 미분 적분", "start": 0.0, "duration": 5.0},
                    {"text": "미분의 기본 개념을 알아보겠습니다", "start": 5.0, "duration": 5.0},
                ],
                "v_math_2025_w2": [
                    {"text": "적분의 기본 원리를 설명합니다", "start": 0.0, "duration": 5.0},
                ],
                # 2026 videos — w1 is identical (reuse!), w2 is different
                "v_math_2026_w1": [
                    {"text": "오늘 수학 강의 시작하겠습니다 미분 적분", "start": 0.0, "duration": 5.0},
                    {"text": "미분의 기본 개념을 알아보겠습니다", "start": 5.0, "duration": 5.0},
                ],
                "v_math_2026_w2": [
                    {"text": "적분의 응용과 새로운 접근 방법을 다룹니다", "start": 0.0, "duration": 5.0},
                ],
            },
            "parsed_titles": [
                {"video_id": "v_math_2025_w1", "professor": ["Kim"], "course": "Math", "week": 1, "session": 1, "year": 2025, "parse_error": False},
                {"video_id": "v_math_2025_w2", "professor": ["Kim"], "course": "Math", "week": 2, "session": 1, "year": 2025, "parse_error": False},
                {"video_id": "v_math_2026_w1", "professor": ["Kim"], "course": "Math", "week": 1, "session": 1, "year": 2026, "parse_error": False},
                {"video_id": "v_math_2026_w2", "professor": ["Kim"], "course": "Math", "week": 2, "session": 1, "year": 2026, "parse_error": False},
            ],
            "durations": {
                "v_math_2025_w1": 600,
                "v_math_2025_w2": 300,
                "v_math_2026_w1": 600,
                "v_math_2026_w2": 350,
            },
        }

    def test_full_pipeline(self, db: ContentDB, project_dir: Path) -> None:
        """Test complete pipeline from fingerprint to report."""
        data = self._create_test_data()
        fp_service = FingerprintService()

        # ── Stage 1: Fingerprint ──
        for vid, segments in data["transcripts"].items():
            fp = fp_service.generate_hash(segments)
            db.upsert_fingerprint(vid, fp.sha256_hash, fp.full_text_length)
            db.upsert_processing_status(vid, "channel1", "fingerprinted")

        # Verify fingerprints stored
        assert db.get_fingerprint("v_math_2025_w1") is not None
        assert db.get_fingerprint("v_math_2026_w1") is not None

        # Verify identical captions have same hash
        fp_2025 = db.get_fingerprint("v_math_2025_w1")
        fp_2026 = db.get_fingerprint("v_math_2026_w1")
        assert fp_2025["sha256_hash"] == fp_2026["sha256_hash"]

        # ── Stage 2: Compare ──
        pairs = match_comparison_pairs(
            data["parsed_titles"], year_from=2025, year_to=2026
        )
        assert len(pairs) == 2  # w1 and w2

        # Build lookups
        text_map = {
            vid: fp_service.extract_full_text(segs)
            for vid, segs in data["transcripts"].items()
        }
        dur_map = data["durations"]

        comparator = ContentComparator(
            fingerprint_lookup=lambda vid: db.get_fingerprint(vid),
            text_lookup=lambda vid: text_map.get(vid),
            duration_lookup=lambda vid: dur_map.get(vid),
        )

        for pair in pairs:
            result = comparator.compare_pair(pair)
            db.insert_comparison(**{
                k: result[k] for k in [
                    "source_video_id", "target_video_id", "professor", "course",
                    "week", "session", "year_from", "year_to",
                    "i1_hash_match", "i2_cosine_similarity", "i3_change_rate",
                    "i4_new_term_count", "i5_duration_diff_seconds",
                    "suspicion_score", "grade",
                ]
            })

        # Verify comparisons stored
        comparisons = db.list_comparisons(order_by_suspicion=True)
        assert len(comparisons) == 2

        # Week 1 (identical) should have higher suspicion than week 2 (different)
        w1_comp = [c for c in comparisons if c["week"] == 1][0]
        w2_comp = [c for c in comparisons if c["week"] == 2][0]
        assert w1_comp["i1_hash_match"] == 1  # Identical content
        assert w1_comp["suspicion_score"] > w2_comp["suspicion_score"]
        assert w1_comp["grade"] in ("critical", "high")

        # ── Stage 3: Quality ──
        checker = QualityChecker()
        for vid, segments in data["transcripts"].items():
            duration = dur_map.get(vid, 0)
            result = checker.run_all_checks(
                segments=segments, duration_seconds=duration, course_name="Math"
            )
            db.upsert_quality_result(
                video_id=vid,
                q001_voice_present=result.q001_voice_present,
                q002_min_duration=result.q002_min_duration,
                q003_course_relevance=result.q003_course_relevance,
                q004_silence_ratio=result.q004_silence_ratio,
                q005_speech_density=result.q005_speech_density,
                pass_count=result.pass_count,
            )

        q_result = db.get_quality_result("v_math_2025_w1")
        assert q_result is not None
        assert q_result["q001_voice_present"] == 1

        # ── Stage 4: Review ──
        db.update_review_status(w1_comp["id"], "CONFIRMED_DUPLICATE", reviewed_by="admin")
        updated = db.get_comparison(w1_comp["id"])
        assert updated["review_status"] == "CONFIRMED_DUPLICATE"

        # Verify confirmed pair excluded from unreviewed list
        unreviewed = db.list_comparisons(review_status="UNREVIEWED")
        assert len(unreviewed) == 1
        assert unreviewed[0]["week"] == 2

        # ── Stage 5: Report ──
        all_comparisons = db.list_comparisons(order_by_suspicion=True)

        # Collect quality results
        quality_results = []
        for vid in data["transcripts"]:
            qr = db.get_quality_result(vid)
            if qr:
                quality_results.append(qr)

        generator = ContentReportGenerator()

        # JSON report
        json_path = project_dir / "report.json"
        generator.generate_json(all_comparisons, quality_results, json_path)
        assert json_path.exists()
        json_data = json.loads(json_path.read_text())
        assert json_data["summary"]["total_comparisons"] == 2
        assert json_data["summary"]["grade_counts"]["critical"] + json_data["summary"]["grade_counts"]["high"] >= 1

        # HTML report
        html_path = project_dir / "report.html"
        generator.generate_html(all_comparisons, quality_results, html_path)
        assert html_path.exists()
        html_content = html_path.read_text()
        assert "Kim" in html_content

        # Excel report
        xlsx_path = project_dir / "report.xlsx"
        generator.generate_xlsx(all_comparisons, quality_results, xlsx_path)
        assert xlsx_path.exists()
        assert xlsx_path.stat().st_size > 0
