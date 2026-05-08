"""Integration test for fingerprint -> compare pipeline."""

from pathlib import Path

import pytest

from tube_scout.services.content_comparator import (
    ContentComparator,
    match_comparison_pairs,
)
from tube_scout.services.fingerprint import FingerprintService
from tube_scout.services.quality_checker import QualityChecker
from tube_scout.storage.content_db import ContentDB


@pytest.fixture()
def db(tmp_path: Path) -> ContentDB:
    """Create a test database."""
    return ContentDB(tmp_path / "test.db")


@pytest.fixture()
def fingerprint_service() -> FingerprintService:
    """Create a fingerprint service."""
    return FingerprintService()


class TestFingerprintComparePipeline:
    """End-to-end test for fingerprint -> compare flow."""

    def test_identical_captions_detected(
        self, db: ContentDB, fingerprint_service: FingerprintService
    ) -> None:
        """Identical caption text should produce hash match and critical grade."""
        # Setup: Two videos with identical captions
        segments = [
            {"text": "이것은 테스트 강의입니다", "start": 0.0, "duration": 5.0},
            {"text": "오늘의 주제는 수학입니다", "start": 5.0, "duration": 5.0},
        ]

        # Step 1: Generate fingerprints
        fp_v1 = fingerprint_service.generate_hash(segments)
        fp_v2 = fingerprint_service.generate_hash(segments)

        # Store in DB
        db.upsert_fingerprint("v1", fp_v1.sha256_hash, fp_v1.full_text_length)
        db.upsert_fingerprint("v2", fp_v2.sha256_hash, fp_v2.full_text_length)

        # Step 2: Match pairs
        parsed_titles = [
            {"video_id": "v1", "professor": ["Kim"], "course": "Math",
             "week": 1, "session": 1, "year": 2025, "parse_error": False},
            {"video_id": "v2", "professor": ["Kim"], "course": "Math",
             "week": 1, "session": 1, "year": 2026, "parse_error": False},
        ]
        pairs = match_comparison_pairs(parsed_titles, year_from=2025, year_to=2026)
        assert len(pairs) == 1

        # Step 3: Compare with indicators
        full_text = fingerprint_service.extract_full_text(segments)
        text_map = {"v1": full_text, "v2": full_text}
        fp_map = {"v1": db.get_fingerprint("v1"), "v2": db.get_fingerprint("v2")}
        dur_map = {"v1": 600.0, "v2": 600.0}

        comparator = ContentComparator(
            fingerprint_lookup=lambda vid: fp_map.get(vid),
            text_lookup=lambda vid: text_map.get(vid),
            duration_lookup=lambda vid: dur_map.get(vid),
        )
        result = comparator.compare_pair(pairs[0])

        assert result["i1_hash_match"] is True
        # Without embedding model, i2_cosine=0, so max score is 75 (30+20+15+10)
        # With embeddings the score would be 100 (critical)
        assert result["suspicion_score"] >= 60.0
        assert result["grade"] in ("critical", "high")

        # Step 4: Store in DB
        comp_id = db.insert_comparison(**{
            k: result[k] for k in [
                "source_video_id", "target_video_id", "professor", "course",
                "week", "session", "year_from", "year_to",
                "i1_hash_match", "i2_cosine_similarity", "i3_change_rate",
                "i4_new_term_count", "i5_duration_diff_seconds",
                "suspicion_score", "grade",
            ]
        })
        stored = db.get_comparison(comp_id)
        assert stored is not None
        assert stored["grade"] in ("critical", "high")

    def test_different_captions_normal(
        self, db: ContentDB, fingerprint_service: FingerprintService
    ) -> None:
        """Completely different captions should produce normal grade."""
        segments_v1 = [
            {"text": "첫 번째 강의 내용입니다", "start": 0.0, "duration": 5.0},
        ]
        segments_v2 = [
            {"text": "완전히 새로운 두 번째 강의", "start": 0.0, "duration": 5.0},
        ]

        fp_v1 = fingerprint_service.generate_hash(segments_v1)
        fp_v2 = fingerprint_service.generate_hash(segments_v2)

        db.upsert_fingerprint("v1", fp_v1.sha256_hash, fp_v1.full_text_length)
        db.upsert_fingerprint("v2", fp_v2.sha256_hash, fp_v2.full_text_length)

        text_v1 = fingerprint_service.extract_full_text(segments_v1)
        text_v2 = fingerprint_service.extract_full_text(segments_v2)

        comparator = ContentComparator(
            fingerprint_lookup=lambda vid: db.get_fingerprint(vid),
            text_lookup=lambda vid: {"v1": text_v1, "v2": text_v2}.get(vid),
            duration_lookup=lambda vid: {"v1": 600.0, "v2": 900.0}.get(vid),
        )

        pair = {
            "source_video_id": "v1", "target_video_id": "v2",
            "professor": "Lee", "course": "Physics",
            "week": 1, "session": 1, "year_from": 2025, "year_to": 2026,
        }
        result = comparator.compare_pair(pair)

        assert result["i1_hash_match"] is False
        assert result["i3_change_rate"] > 0.5
        assert result["grade"] in ("normal", "moderate")


class TestFullPipelineWithQuality:
    """Integration test including quality checks."""

    def test_quality_check_integration(self, db: ContentDB) -> None:
        """Quality checker results should be storable in DB."""
        checker = QualityChecker()
        segments = [
            {"text": "해부학 관련 강의 내용 " * 50, "start": 0.0, "duration": 300.0},
        ]
        result = checker.run_all_checks(
            segments=segments,
            duration_seconds=600,
            course_name="해부학",
        )

        db.upsert_quality_result(
            video_id="v1",
            q001_voice_present=result.q001_voice_present,
            q002_min_duration=result.q002_min_duration,
            q003_course_relevance=result.q003_course_relevance,
            q004_silence_ratio=result.q004_silence_ratio,
            q005_speech_density=result.q005_speech_density,
            pass_count=result.pass_count,
        )

        stored = db.get_quality_result("v1")
        assert stored is not None
        assert stored["pass_count"] == result.pass_count
