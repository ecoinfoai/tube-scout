"""Adversary tests for validation edge cases (T050)."""

from tube_scout.models.parsed_title import ParsedTitle
from tube_scout.services.validator import (
    check_duplicates,
    check_missing_weeks,
    check_session_gaps,
    run_all_validations,
)


def _make_parsed(
    video_id: str = "v1",
    title: str = "test title",
    professor: list[str] | None = None,
    course: str | None = "TestCourse",
    year: int | None = 2024,
    semester: int | None = 1,
    week: int | None = 1,
    session: int | None = 1,
    department: str | None = None,
    category: str = "regular",
    parse_error: bool = False,
    matched_pattern: str | None = "standard_kr",
) -> ParsedTitle:
    """Helper to create ParsedTitle with defaults."""
    return ParsedTitle(
        video_id=video_id,
        original_title=title,
        professor=professor if professor is not None else ["홍길동"],
        course=course,
        year=year,
        semester=semester,
        week=week,
        session=session,
        department=department,
        category=category,
        parse_error=parse_error,
        matched_pattern=matched_pattern,
    )


def _make_video(
    video_id: str = "v1",
    published_at: str = "2024-03-15T10:00:00Z",
    duration_seconds: int = 3600,
) -> dict:
    """Helper to create video metadata dict."""
    return {
        "video_id": video_id,
        "published_at": published_at,
        "duration_seconds": duration_seconds,
    }


class TestAllValidData:
    """When all data is perfectly valid, no findings should be returned."""

    def test_no_findings_for_perfect_data(self) -> None:
        parsed = [
            _make_parsed(video_id=f"v{i}", week=i, session=1) for i in range(1, 6)
        ]
        videos = [
            _make_video(
                video_id=f"v{i}",
                published_at=f"2024-03-{i:02d}T10:00:00Z",
            )
            for i in range(1, 6)
        ]
        findings = run_all_validations(parsed, videos)
        assert findings == []


class TestSupplementaryOnly:
    """When all videos are supplementary."""

    def test_supplementary_not_flagged_for_missing_weeks(self) -> None:
        parsed = [
            _make_parsed(
                video_id=f"v{i}",
                week=i * 3,
                session=1,
                category="supplementary",
            )
            for i in range(1, 4)
        ]
        findings = check_missing_weeks(parsed)
        # Supplementary videos should not trigger missing weeks
        assert findings == []

    def test_supplementary_not_flagged_for_session_gaps(self) -> None:
        parsed = [
            _make_parsed(
                video_id="v1",
                week=1,
                session=3,
                category="supplementary",
            ),
        ]
        findings = check_session_gaps(parsed)
        assert findings == []


class TestSingleVideo:
    """Edge case with only one video."""

    def test_single_video_no_duplicates(self) -> None:
        parsed = [_make_parsed(video_id="v1")]
        findings = check_duplicates(parsed)
        assert findings == []

    def test_single_video_no_missing_weeks(self) -> None:
        parsed = [_make_parsed(video_id="v1", week=5)]
        findings = check_missing_weeks(parsed)
        assert findings == []

    def test_single_video_run_all(self) -> None:
        parsed = [_make_parsed(video_id="v1")]
        videos = [_make_video(video_id="v1")]
        findings = run_all_validations(parsed, videos)
        assert isinstance(findings, list)


class TestNoCalendar:
    """Validation without academic calendar."""

    def test_run_all_without_calendar(self) -> None:
        parsed = [
            _make_parsed(video_id="v1", week=1, session=1),
            _make_parsed(video_id="v2", week=2, session=1),
        ]
        videos = [
            _make_video(video_id="v1", published_at="2024-03-01T10:00:00Z"),
            _make_video(video_id="v2", published_at="2024-03-08T10:00:00Z"),
        ]
        findings = run_all_validations(parsed, videos, calendar=None)
        assert isinstance(findings, list)


class TestEmptyInputs:
    """Validation with empty inputs."""

    def test_empty_parsed_titles(self) -> None:
        findings = run_all_validations([], [])
        assert findings == []

    def test_empty_parsed_no_crash(self) -> None:
        findings = check_duplicates([])
        assert findings == []

    def test_empty_missing_weeks(self) -> None:
        findings = check_missing_weeks([])
        assert findings == []


class TestVideoIdMismatch:
    """Videos metadata may not match parsed titles exactly."""

    def test_missing_video_metadata_no_crash(self) -> None:
        parsed = [_make_parsed(video_id="v1", year=2020)]
        # No matching video in videos list
        videos = [_make_video(video_id="v999")]
        # Should not crash — year mismatch check skips unmatched
        findings = run_all_validations(parsed, videos)
        assert isinstance(findings, list)
