"""Tests for SQLite content database wrapper."""

import sqlite3
from pathlib import Path

import pytest

from tube_scout.storage.content_db import ContentDB


@pytest.fixture()
def db(tmp_path: Path) -> ContentDB:
    """Create a ContentDB instance with a temp database."""
    return ContentDB(tmp_path / "test.db")


class TestContentDBInit:
    """Tests for database initialization."""

    def test_creates_database_file(self, tmp_path: Path) -> None:
        db_path = tmp_path / "new.db"
        ContentDB(db_path)
        assert db_path.exists()

    def test_creates_all_tables(self, db: ContentDB) -> None:
        conn = sqlite3.connect(str(db.db_path))
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        tables = {row[0] for row in cursor.fetchall()}
        conn.close()
        assert "processing_status" in tables
        assert "fingerprint_hashes" in tables
        assert "comparison_results" in tables
        assert "quality_results" in tables

    def test_creates_parent_directories(self, tmp_path: Path) -> None:
        db_path = tmp_path / "nested" / "dirs" / "test.db"
        ContentDB(db_path)
        assert db_path.exists()


class TestProcessingStatusCRUD:
    """Tests for processing_status table operations."""

    def test_upsert_and_get(self, db: ContentDB) -> None:
        db.upsert_processing_status("v1", "c1", "pending")
        result = db.get_processing_status("v1")
        assert result is not None
        assert result["video_id"] == "v1"
        assert result["channel_id"] == "c1"
        assert result["status"] == "pending"

    def test_upsert_updates_existing(self, db: ContentDB) -> None:
        db.upsert_processing_status("v1", "c1", "pending")
        db.upsert_processing_status("v1", "c1", "collected", caption_source="captions_api")
        result = db.get_processing_status("v1")
        assert result is not None
        assert result["status"] == "collected"
        assert result["caption_source"] == "captions_api"

    def test_get_nonexistent(self, db: ContentDB) -> None:
        result = db.get_processing_status("nonexistent")
        assert result is None

    def test_list_by_status(self, db: ContentDB) -> None:
        db.upsert_processing_status("v1", "c1", "pending")
        db.upsert_processing_status("v2", "c1", "collected")
        db.upsert_processing_status("v3", "c1", "pending")
        results = db.list_processing_status(status="pending")
        assert len(results) == 2
        video_ids = {r["video_id"] for r in results}
        assert video_ids == {"v1", "v3"}

    def test_list_by_channel(self, db: ContentDB) -> None:
        db.upsert_processing_status("v1", "c1", "pending")
        db.upsert_processing_status("v2", "c2", "pending")
        results = db.list_processing_status(channel_id="c1")
        assert len(results) == 1
        assert results[0]["video_id"] == "v1"


class TestFingerprintCRUD:
    """Tests for fingerprint_hashes table operations."""

    def test_insert_and_get(self, db: ContentDB) -> None:
        db.upsert_fingerprint("v1", "a" * 64, 1000)
        result = db.get_fingerprint("v1")
        assert result is not None
        assert result["sha256_hash"] == "a" * 64
        assert result["full_text_length"] == 1000

    def test_upsert_updates_existing(self, db: ContentDB) -> None:
        db.upsert_fingerprint("v1", "a" * 64, 1000)
        db.upsert_fingerprint("v1", "b" * 64, 2000, embedding_row_index=5)
        result = db.get_fingerprint("v1")
        assert result is not None
        assert result["sha256_hash"] == "b" * 64
        assert result["full_text_length"] == 2000
        assert result["embedding_row_index"] == 5

    def test_get_nonexistent(self, db: ContentDB) -> None:
        result = db.get_fingerprint("nonexistent")
        assert result is None

    def test_find_by_hash(self, db: ContentDB) -> None:
        hash_val = "c" * 64
        db.upsert_fingerprint("v1", hash_val, 500)
        db.upsert_fingerprint("v2", hash_val, 500)
        db.upsert_fingerprint("v3", "d" * 64, 600)
        results = db.find_by_hash(hash_val)
        assert len(results) == 2
        video_ids = {r["video_id"] for r in results}
        assert video_ids == {"v1", "v2"}


class TestComparisonResultCRUD:
    """Tests for comparison_results table operations."""

    def test_insert_and_get(self, db: ContentDB) -> None:
        comp_id = db.insert_comparison(
            source_video_id="v1",
            target_video_id="v2",
            professor="Kim",
            course="Math101",
            week=1,
            session=1,
            year_from=2025,
            year_to=2026,
            i1_hash_match=False,
            i2_cosine_similarity=0.85,
            i3_change_rate=0.15,
            i4_new_term_count=5,
            i5_duration_diff_seconds=30.0,
            suspicion_score=65.0,
            grade="high",
        )
        assert comp_id > 0
        result = db.get_comparison(comp_id)
        assert result is not None
        assert result["professor"] == "Kim"
        assert result["suspicion_score"] == pytest.approx(65.0)
        assert result["grade"] == "high"
        assert result["review_status"] == "UNREVIEWED"

    def test_unique_constraint(self, db: ContentDB) -> None:
        db.insert_comparison(
            source_video_id="v1",
            target_video_id="v2",
            professor="Kim",
            course="Math",
            week=1,
            session=1,
            year_from=2025,
            year_to=2026,
        )
        with pytest.raises(sqlite3.IntegrityError):
            db.insert_comparison(
                source_video_id="v1",
                target_video_id="v2",
                professor="Kim",
                course="Math",
                week=1,
                session=1,
                year_from=2025,
                year_to=2026,
            )

    def test_list_by_review_status(self, db: ContentDB) -> None:
        db.insert_comparison(
            source_video_id="v1", target_video_id="v2",
            professor="Kim", course="Math", week=1, session=1,
            year_from=2025, year_to=2026, suspicion_score=80.0, grade="critical",
        )
        db.insert_comparison(
            source_video_id="v3", target_video_id="v4",
            professor="Lee", course="Phys", week=1, session=1,
            year_from=2025, year_to=2026, suspicion_score=50.0, grade="moderate",
        )
        results = db.list_comparisons(review_status="UNREVIEWED")
        assert len(results) == 2

    def test_list_by_grade(self, db: ContentDB) -> None:
        db.insert_comparison(
            source_video_id="v1", target_video_id="v2",
            professor="Kim", course="Math", week=1, session=1,
            year_from=2025, year_to=2026, suspicion_score=85.0, grade="critical",
        )
        db.insert_comparison(
            source_video_id="v3", target_video_id="v4",
            professor="Lee", course="Phys", week=1, session=1,
            year_from=2025, year_to=2026, suspicion_score=50.0, grade="moderate",
        )
        results = db.list_comparisons(grade="critical")
        assert len(results) == 1
        assert results[0]["professor"] == "Kim"

    def test_update_review_status(self, db: ContentDB) -> None:
        comp_id = db.insert_comparison(
            source_video_id="v1", target_video_id="v2",
            professor="Kim", course="Math", week=1, session=1,
            year_from=2025, year_to=2026,
        )
        db.update_review_status(comp_id, "CONFIRMED_DUPLICATE", reviewed_by="admin")
        result = db.get_comparison(comp_id)
        assert result is not None
        assert result["review_status"] == "CONFIRMED_DUPLICATE"
        assert result["reviewed_by"] == "admin"
        assert result["reviewed_at"] is not None

    def test_list_sorted_by_suspicion(self, db: ContentDB) -> None:
        db.insert_comparison(
            source_video_id="v1", target_video_id="v2",
            professor="Kim", course="Math", week=1, session=1,
            year_from=2025, year_to=2026, suspicion_score=50.0, grade="moderate",
        )
        db.insert_comparison(
            source_video_id="v3", target_video_id="v4",
            professor="Lee", course="Phys", week=1, session=1,
            year_from=2025, year_to=2026, suspicion_score=90.0, grade="critical",
        )
        results = db.list_comparisons(order_by_suspicion=True)
        assert len(results) == 2
        assert results[0]["suspicion_score"] == pytest.approx(90.0)
        assert results[1]["suspicion_score"] == pytest.approx(50.0)


class TestQualityResultCRUD:
    """Tests for quality_results table operations."""

    def test_upsert_and_get(self, db: ContentDB) -> None:
        db.upsert_quality_result(
            video_id="v1",
            q001_voice_present=True,
            q002_min_duration=True,
            q003_course_relevance=0.5,
            q004_silence_ratio=0.1,
            q005_speech_density=350.0,
            pass_count=5,
        )
        result = db.get_quality_result("v1")
        assert result is not None
        assert result["q001_voice_present"] == 1  # SQLite bool
        assert result["pass_count"] == 5

    def test_get_nonexistent(self, db: ContentDB) -> None:
        result = db.get_quality_result("nonexistent")
        assert result is None

    def test_upsert_updates_existing(self, db: ContentDB) -> None:
        db.upsert_quality_result(video_id="v1", pass_count=3)
        db.upsert_quality_result(video_id="v1", pass_count=5)
        result = db.get_quality_result("v1")
        assert result is not None
        assert result["pass_count"] == 5
