"""Tests for content review CLI operations."""

from pathlib import Path

import pytest

from tube_scout.storage.content_db import ContentDB


class TestReviewWorkflow:
    """Tests for the review workflow using ContentDB."""

    @pytest.fixture()
    def db_with_comparisons(self, tmp_path: Path) -> ContentDB:
        """Create a DB with pre-loaded comparison results."""
        db = ContentDB(tmp_path / "test.db")
        db.insert_comparison(
            source_video_id="v1", target_video_id="v2",
            professor="Kim", course="Math", week=1, session=1,
            year_from=2025, year_to=2026,
            suspicion_score=90.0, grade="critical",
        )
        db.insert_comparison(
            source_video_id="v3", target_video_id="v4",
            professor="Lee", course="Physics", week=1, session=1,
            year_from=2025, year_to=2026,
            suspicion_score=50.0, grade="moderate",
        )
        db.insert_comparison(
            source_video_id="v5", target_video_id="v6",
            professor="Park", course="Chem", week=1, session=1,
            year_from=2025, year_to=2026,
            suspicion_score=30.0, grade="normal",
        )
        return db

    def test_list_unreviewed_sorted_by_suspicion(
        self, db_with_comparisons: ContentDB
    ) -> None:
        results = db_with_comparisons.list_comparisons(
            review_status="UNREVIEWED", order_by_suspicion=True
        )
        assert len(results) == 3
        assert results[0]["suspicion_score"] == pytest.approx(90.0)
        assert results[1]["suspicion_score"] == pytest.approx(50.0)
        assert results[2]["suspicion_score"] == pytest.approx(30.0)

    def test_list_by_grade(self, db_with_comparisons: ContentDB) -> None:
        results = db_with_comparisons.list_comparisons(grade="critical")
        assert len(results) == 1
        assert results[0]["professor"] == "Kim"

    def test_mark_confirmed_duplicate(
        self, db_with_comparisons: ContentDB
    ) -> None:
        results = db_with_comparisons.list_comparisons(grade="critical")
        comp_id = results[0]["id"]
        db_with_comparisons.update_review_status(
            comp_id, "CONFIRMED_DUPLICATE", reviewed_by="admin"
        )
        updated = db_with_comparisons.get_comparison(comp_id)
        assert updated is not None
        assert updated["review_status"] == "CONFIRMED_DUPLICATE"
        assert updated["reviewed_by"] == "admin"

    def test_mark_false_positive(
        self, db_with_comparisons: ContentDB
    ) -> None:
        results = db_with_comparisons.list_comparisons(grade="moderate")
        comp_id = results[0]["id"]
        db_with_comparisons.update_review_status(
            comp_id, "FALSE_POSITIVE", reviewed_by="admin"
        )
        updated = db_with_comparisons.get_comparison(comp_id)
        assert updated is not None
        assert updated["review_status"] == "FALSE_POSITIVE"

    def test_reviewed_excluded_from_unreviewed_list(
        self, db_with_comparisons: ContentDB
    ) -> None:
        results = db_with_comparisons.list_comparisons(review_status="UNREVIEWED")
        assert len(results) == 3

        comp_id = results[0]["id"]
        db_with_comparisons.update_review_status(comp_id, "CONFIRMED_DUPLICATE")

        results_after = db_with_comparisons.list_comparisons(
            review_status="UNREVIEWED"
        )
        assert len(results_after) == 2

    def test_re_alerting_exclusion(
        self, db_with_comparisons: ContentDB
    ) -> None:
        """Reviewed pairs should be excludable from re-alerting."""
        # Mark first as confirmed
        results = db_with_comparisons.list_comparisons(
            review_status="UNREVIEWED", order_by_suspicion=True
        )
        db_with_comparisons.update_review_status(
            results[0]["id"], "CONFIRMED_DUPLICATE"
        )

        # Query for items that need attention (exclude reviewed)
        unreviewed = db_with_comparisons.list_comparisons(
            review_status="UNREVIEWED"
        )
        reviewed_ids = {r["id"] for r in db_with_comparisons.list_comparisons(
            review_status="CONFIRMED_DUPLICATE"
        )}
        assert results[0]["id"] in reviewed_ids
        assert all(r["id"] not in reviewed_ids for r in unreviewed)
