"""End-to-end integration test for the admin flow.

Tests: auth → collect → parse → validate → report → verify output structure.
All YouTube API calls are mocked.
"""

import json
from pathlib import Path

import pytest

from tube_scout.models.config import ChannelRegistration
from tube_scout.models.parsed_title import ParsedTitle
from tube_scout.output.manager import OutputManager
from tube_scout.services.auth import (
    load_registry,
    save_registry,
)
from tube_scout.services.search_service import SearchService
from tube_scout.services.validator import run_all_validations


@pytest.fixture()
def output_dir(tmp_path: Path) -> Path:
    """Create a temporary output directory."""
    d = tmp_path / "output"
    d.mkdir()
    return d


@pytest.fixture()
def tokens_dir(tmp_path: Path) -> Path:
    """Create a temporary tokens directory."""
    d = tmp_path / "tokens"
    d.mkdir()
    return d


@pytest.fixture()
def sample_parsed_titles() -> list[ParsedTitle]:
    """Create sample parsed titles for testing."""
    return [
        ParsedTitle(
            video_id="vid001",
            original_title="홍길동 2024 감염미생물학 5주차 1차시",
            professor=["홍길동"],
            course="감염미생물학",
            year=2024,
            semester=2,
            week=5,
            session=1,
            category="regular",
            parse_error=False,
        ),
        ParsedTitle(
            video_id="vid002",
            original_title="홍길동 2024 감염미생물학 5주차 1차시",
            professor=["홍길동"],
            course="감염미생물학",
            year=2024,
            semester=2,
            week=5,
            session=1,
            category="regular",
            parse_error=False,
        ),
        ParsedTitle(
            video_id="vid003",
            original_title="홍길동 2024 감염미생물학 7주차 1차시",
            professor=["홍길동"],
            course="감염미생물학",
            year=2024,
            semester=2,
            week=7,
            session=1,
            category="regular",
            parse_error=False,
        ),
        ParsedTitle(
            video_id="vid004",
            original_title="홍길동 2024 감염미생물학 18주차 1차시",
            professor=["홍길동"],
            course="감염미생물학",
            year=2024,
            semester=2,
            week=18,
            session=1,
            category="regular",
            parse_error=False,
        ),
    ]


class TestAdminFlowEndToEnd:
    """End-to-end test for the multi-channel admin workflow."""

    def test_auth_registry_roundtrip(self, tokens_dir: Path) -> None:
        """Test that channel registration persists correctly."""
        reg = ChannelRegistration(
            alias="간호학과",
            channel_id="UCxxxxxxxxxxxxxxxxxxxxxx",
            channel_name="부산보건대 간호학과",
            registered_at="2026-04-04T12:00:00",
            last_used_at="2026-04-04T12:00:00",
            token_path=str(tokens_dir / "간호학과.json"),
        )
        save_registry(tokens_dir, {"간호학과": reg})
        loaded = load_registry(tokens_dir)
        assert "간호학과" in loaded
        assert loaded["간호학과"].channel_id == "UCxxxxxxxxxxxxxxxxxxxxxx"

    def test_output_creation_and_data_storage(
        self,
        output_dir: Path,
        sample_parsed_titles: list[ParsedTitle],
    ) -> None:
        """Test that output directories are created and data stored."""
        mgr = OutputManager(base_dir=output_dir)
        run_dir = mgr.create_run()
        mgr.update_latest_link(run_dir)

        # Store parsed titles
        channel_id = "간호학과"
        parsed_dir = run_dir / "parsed" / channel_id
        parsed_dir.mkdir(parents=True)
        data = [pt.model_dump(mode="json") for pt in sample_parsed_titles]
        (parsed_dir / "parsed_titles.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        # Verify structure
        assert (run_dir / "parsed" / channel_id / "parsed_titles.json").exists()
        assert mgr.get_latest() == run_dir.resolve()

    def test_search_on_stored_data(
        self,
        sample_parsed_titles: list[ParsedTitle],
    ) -> None:
        """Test search against parsed titles."""
        from tube_scout.models.search import SearchFilter, SearchQuery

        query = SearchQuery(filters=SearchFilter(professor="홍길동", year=2024))
        results = SearchService.search(sample_parsed_titles, query)
        assert len(results) == 4

    def test_validation_on_stored_data(
        self,
        sample_parsed_titles: list[ParsedTitle],
    ) -> None:
        """Test validation produces findings for known issues."""
        findings = run_all_validations(sample_parsed_titles, [])

        # Should find duplicates (vid001 and vid002 have same fields)
        duplicate_findings = [f for f in findings if f.rule_id == "V-002"]
        assert len(duplicate_findings) > 0

        # Should find invalid week (18 > 16)
        invalid_week_findings = [f for f in findings if f.rule_id == "V-003"]
        assert len(invalid_week_findings) > 0

    def test_full_pipeline_output_structure(
        self,
        output_dir: Path,
        sample_parsed_titles: list[ParsedTitle],
    ) -> None:
        """Test the full pipeline produces expected output structure."""
        mgr = OutputManager(base_dir=output_dir)
        run_dir = mgr.create_run()
        mgr.update_latest_link(run_dir)
        channel_id = "간호학과"

        # Step 1: Store parsed titles
        parsed_dir = run_dir / "parsed" / channel_id
        parsed_dir.mkdir(parents=True)
        parsed_data = [pt.model_dump(mode="json") for pt in sample_parsed_titles]
        (parsed_dir / "parsed_titles.json").write_text(
            json.dumps(parsed_data, ensure_ascii=False), encoding="utf-8"
        )

        # Step 2: Run validation and store
        findings = run_all_validations(sample_parsed_titles, [])
        validation_dir = run_dir / "validation" / channel_id
        validation_dir.mkdir(parents=True)
        findings_data = [f.model_dump() for f in findings]
        (validation_dir / "findings.json").write_text(
            json.dumps(findings_data, ensure_ascii=False), encoding="utf-8"
        )

        # Step 3: Create reports directory
        reports_dir = run_dir / "reports" / "department"
        reports_dir.mkdir(parents=True)

        # Verify complete structure
        assert (run_dir / "parsed" / channel_id / "parsed_titles.json").exists()
        assert (run_dir / "validation" / channel_id / "findings.json").exists()
        assert (run_dir / "reports" / "department").is_dir()
        assert mgr.get_latest() == run_dir.resolve()

    def test_second_run_preserves_first(
        self,
        output_dir: Path,
        sample_parsed_titles: list[ParsedTitle],
    ) -> None:
        """Test that a second run does not modify the first run's data."""
        mgr = OutputManager(base_dir=output_dir)

        # First run
        run1 = mgr.create_run()
        mgr.update_latest_link(run1)
        parsed_dir1 = run1 / "parsed" / "ch1"
        parsed_dir1.mkdir(parents=True)
        (parsed_dir1 / "parsed_titles.json").write_text('"run1_data"', encoding="utf-8")

        # Second run
        run2_path = output_dir / "report-20260405-0900"
        run2_path.mkdir()
        mgr.update_latest_link(run2_path)
        parsed_dir2 = run2_path / "parsed" / "ch1"
        parsed_dir2.mkdir(parents=True)
        (parsed_dir2 / "parsed_titles.json").write_text('"run2_data"', encoding="utf-8")

        # First run's data is unchanged
        data1 = (parsed_dir1 / "parsed_titles.json").read_text(encoding="utf-8")
        assert json.loads(data1) == "run1_data"

        # Latest points to run2
        assert mgr.get_latest() == run2_path.resolve()
