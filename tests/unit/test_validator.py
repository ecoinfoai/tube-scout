"""Tests for title validation rules (T049)."""


from tube_scout.models.parsed_title import ParsedTitle
from tube_scout.services.validator import (
    check_duplicates,
    check_duration_outliers,
    check_invalid_week,
    check_missing_weeks,
    check_name_inconsistency,
    check_parse_failures,
    check_session_gaps,
    check_upload_gaps,
    check_year_mismatch,
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


class TestCheckYearMismatch:
    """V-001: title year vs upload year difference > 1."""

    def test_no_mismatch(self) -> None:
        parsed = [_make_parsed(video_id="v1", year=2024)]
        videos = [_make_video(video_id="v1", published_at="2024-03-15T10:00:00Z")]
        findings = check_year_mismatch(parsed, videos)
        assert findings == []

    def test_mismatch_detected(self) -> None:
        parsed = [_make_parsed(video_id="v1", year=2020)]
        videos = [_make_video(video_id="v1", published_at="2024-03-15T10:00:00Z")]
        findings = check_year_mismatch(parsed, videos)
        assert len(findings) == 1
        assert findings[0].rule_id == "V-001"
        assert findings[0].severity == "WARNING"
        assert "v1" in findings[0].video_ids

    def test_difference_of_1_is_ok(self) -> None:
        parsed = [_make_parsed(video_id="v1", year=2023)]
        videos = [_make_video(video_id="v1", published_at="2024-01-15T10:00:00Z")]
        findings = check_year_mismatch(parsed, videos)
        assert findings == []

    def test_no_year_skipped(self) -> None:
        parsed = [_make_parsed(video_id="v1", year=None)]
        videos = [_make_video(video_id="v1", published_at="2024-03-15T10:00:00Z")]
        findings = check_year_mismatch(parsed, videos)
        assert findings == []


class TestCheckDuplicates:
    """V-002: same professor+course+week+session combo appears 2+ times."""

    def test_no_duplicates(self) -> None:
        parsed = [
            _make_parsed(video_id="v1", week=1, session=1),
            _make_parsed(video_id="v2", week=1, session=2),
        ]
        findings = check_duplicates(parsed)
        assert findings == []

    def test_duplicate_detected(self) -> None:
        parsed = [
            _make_parsed(video_id="v1", week=1, session=1),
            _make_parsed(video_id="v2", week=1, session=1),
        ]
        findings = check_duplicates(parsed)
        assert len(findings) == 1
        assert findings[0].rule_id == "V-002"
        assert findings[0].severity == "ERROR"
        assert set(findings[0].video_ids) == {"v1", "v2"}

    def test_different_professors_not_duplicate(self) -> None:
        parsed = [
            _make_parsed(video_id="v1", professor=["홍길동"], week=1, session=1),
            _make_parsed(video_id="v2", professor=["김영수"], week=1, session=1),
        ]
        findings = check_duplicates(parsed)
        assert findings == []

    def test_missing_fields_skipped(self) -> None:
        parsed = [
            _make_parsed(video_id="v1", week=None, session=None),
            _make_parsed(video_id="v2", week=None, session=None),
        ]
        findings = check_duplicates(parsed)
        assert findings == []


class TestCheckInvalidWeek:
    """V-003: week > 16 or week <= 0."""

    def test_valid_weeks(self) -> None:
        parsed = [
            _make_parsed(video_id="v1", week=1),
            _make_parsed(video_id="v2", week=16),
        ]
        findings = check_invalid_week(parsed)
        assert findings == []

    def test_week_over_16(self) -> None:
        parsed = [_make_parsed(video_id="v1", week=18)]
        findings = check_invalid_week(parsed)
        assert len(findings) == 1
        assert findings[0].rule_id == "V-003"
        assert findings[0].severity == "ERROR"

    def test_week_zero(self) -> None:
        parsed = [_make_parsed(video_id="v1", week=0)]
        findings = check_invalid_week(parsed)
        assert len(findings) == 1
        assert findings[0].rule_id == "V-003"

    def test_week_none_skipped(self) -> None:
        parsed = [_make_parsed(video_id="v1", week=None)]
        findings = check_invalid_week(parsed)
        assert findings == []


class TestCheckNameInconsistency:
    """V-004: professor names with Levenshtein distance <= 2."""

    def test_no_inconsistency(self) -> None:
        parsed = [
            _make_parsed(video_id="v1", professor=["홍길동"]),
            _make_parsed(video_id="v2", professor=["김영수"]),
        ]
        findings = check_name_inconsistency(parsed)
        assert findings == []

    def test_inconsistency_detected(self) -> None:
        parsed = [
            _make_parsed(video_id="v1", professor=["홍길동"]),
            _make_parsed(video_id="v2", professor=["홍길 동"]),
        ]
        findings = check_name_inconsistency(parsed)
        assert len(findings) == 1
        assert findings[0].rule_id == "V-004"
        assert findings[0].severity == "WARNING"

    def test_identical_names_not_flagged(self) -> None:
        parsed = [
            _make_parsed(video_id="v1", professor=["홍길동"]),
            _make_parsed(video_id="v2", professor=["홍길동"]),
        ]
        findings = check_name_inconsistency(parsed)
        assert findings == []


class TestCheckParseFailures:
    """V-005: titles with parse_error=True."""

    def test_no_failures(self) -> None:
        parsed = [_make_parsed(video_id="v1", parse_error=False)]
        findings = check_parse_failures(parsed)
        assert findings == []

    def test_failure_detected(self) -> None:
        parsed = [
            _make_parsed(video_id="v1", parse_error=True, matched_pattern=None),
        ]
        findings = check_parse_failures(parsed)
        assert len(findings) == 1
        assert findings[0].rule_id == "V-005"
        assert findings[0].severity == "WARNING"

    def test_multiple_failures(self) -> None:
        parsed = [
            _make_parsed(video_id="v1", parse_error=True, matched_pattern=None),
            _make_parsed(video_id="v2", parse_error=True, matched_pattern=None),
            _make_parsed(video_id="v3", parse_error=False),
        ]
        findings = check_parse_failures(parsed)
        assert len(findings) == 2


class TestCheckSessionGaps:
    """V-006: session 2 exists but session 1 missing for same prof+course+week."""

    def test_no_gaps(self) -> None:
        parsed = [
            _make_parsed(video_id="v1", week=1, session=1),
            _make_parsed(video_id="v2", week=1, session=2),
        ]
        findings = check_session_gaps(parsed)
        assert findings == []

    def test_gap_detected(self) -> None:
        parsed = [
            _make_parsed(video_id="v1", week=1, session=2),
        ]
        findings = check_session_gaps(parsed)
        assert len(findings) == 1
        assert findings[0].rule_id == "V-006"
        assert findings[0].severity == "WARNING"

    def test_session_none_skipped(self) -> None:
        parsed = [_make_parsed(video_id="v1", week=1, session=None)]
        findings = check_session_gaps(parsed)
        assert findings == []


class TestCheckDurationOutliers:
    """V-007: duration > +/-3 sigma from course average."""

    def test_no_outliers(self) -> None:
        parsed = [
            _make_parsed(video_id=f"v{i}", course="Math") for i in range(5)
        ]
        videos = [
            _make_video(video_id=f"v{i}", duration_seconds=3600) for i in range(5)
        ]
        findings = check_duration_outliers(parsed, videos)
        assert findings == []

    def test_outlier_detected(self) -> None:
        parsed = [
            _make_parsed(video_id=f"v{i}", course="Math") for i in range(20)
        ]
        videos = [
            _make_video(video_id=f"v{i}", duration_seconds=3600) for i in range(19)
        ]
        # Add extreme outlier (100x normal = definite >3 sigma with 19 normal values)
        videos.append(_make_video(video_id="v19", duration_seconds=360000))
        findings = check_duration_outliers(parsed, videos)
        assert len(findings) >= 1
        assert findings[0].rule_id == "V-007"
        assert findings[0].severity == "INFO"

    def test_too_few_videos_skipped(self) -> None:
        parsed = [_make_parsed(video_id="v1", course="Math")]
        videos = [_make_video(video_id="v1", duration_seconds=3600)]
        findings = check_duration_outliers(parsed, videos)
        assert findings == []


class TestCheckMissingWeeks:
    """V-008: gap in week sequence."""

    def test_no_gaps(self) -> None:
        parsed = [
            _make_parsed(video_id=f"v{i}", week=i) for i in range(1, 5)
        ]
        findings = check_missing_weeks(parsed)
        assert findings == []

    def test_gap_detected(self) -> None:
        parsed = [
            _make_parsed(video_id="v1", week=1),
            _make_parsed(video_id="v2", week=2),
            _make_parsed(video_id="v4", week=4),
            _make_parsed(video_id="v5", week=5),
        ]
        findings = check_missing_weeks(parsed)
        assert len(findings) >= 1
        assert findings[0].rule_id == "V-008"
        assert findings[0].severity == "WARNING"
        assert 3 in findings[0].details.get("missing_weeks", [])

    def test_single_week_no_gap(self) -> None:
        parsed = [_make_parsed(video_id="v1", week=5)]
        findings = check_missing_weeks(parsed)
        assert findings == []


class TestCheckUploadGaps:
    """V-009: 2+ consecutive weeks without upload."""

    def test_no_gaps(self) -> None:
        parsed = [
            _make_parsed(video_id=f"v{i}", week=i) for i in range(1, 5)
        ]
        videos = [
            _make_video(
                video_id=f"v{i}",
                published_at=f"2024-03-{i:02d}T10:00:00Z",
            )
            for i in range(1, 5)
        ]
        findings = check_upload_gaps(parsed, videos)
        assert findings == []

    def test_gap_detected(self) -> None:
        parsed = [
            _make_parsed(video_id="v1", week=1),
            _make_parsed(video_id="v2", week=5),
        ]
        videos = [
            _make_video(video_id="v1", published_at="2024-03-01T10:00:00Z"),
            _make_video(video_id="v2", published_at="2024-04-01T10:00:00Z"),
        ]
        findings = check_upload_gaps(parsed, videos)
        assert len(findings) >= 1
        assert findings[0].rule_id == "V-009"
        assert findings[0].severity == "INFO"


class TestRunAllValidations:
    """Test run_all_validations orchestration."""

    def test_returns_sorted_by_severity(self) -> None:
        parsed = [
            _make_parsed(video_id="v1", week=18),  # V-003 ERROR
            # V-005 WARNING
            _make_parsed(
                video_id="v2", parse_error=True, matched_pattern=None
            ),
        ]
        videos = [
            _make_video(video_id="v1"),
            _make_video(video_id="v2"),
        ]
        findings = run_all_validations(parsed, videos)
        severities = [f.severity for f in findings]
        # ERROR should come before WARNING, WARNING before INFO
        severity_order = {"ERROR": 0, "WARNING": 1, "INFO": 2}
        for i in range(len(severities) - 1):
            assert severity_order[severities[i]] <= severity_order[severities[i + 1]]

    def test_all_clean_returns_empty(self) -> None:
        parsed = [
            _make_parsed(video_id=f"v{i}", week=i, session=1) for i in range(1, 5)
        ]
        videos = [
            _make_video(
                video_id=f"v{i}",
                published_at=f"2024-03-{i:02d}T10:00:00Z",
            )
            for i in range(1, 5)
        ]
        findings = run_all_validations(parsed, videos)
        assert findings == []

    def test_accepts_none_calendar(self) -> None:
        parsed = [_make_parsed(video_id="v1")]
        videos = [_make_video(video_id="v1")]
        findings = run_all_validations(parsed, videos, calendar=None)
        assert isinstance(findings, list)

    def test_supplementary_excluded_from_session_gaps(self) -> None:
        # Supplementary video with session 2 but no session 1 should not trigger V-006
        parsed = [
            _make_parsed(
                video_id="v1", week=1, session=2, category="supplementary"
            ),
        ]
        videos = [_make_video(video_id="v1")]
        findings = run_all_validations(parsed, videos)
        v006_findings = [f for f in findings if f.rule_id == "V-006"]
        assert v006_findings == []
