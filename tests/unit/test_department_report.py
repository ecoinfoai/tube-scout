"""Tests for department report generation (US4 — FR-015~FR-019)."""

from datetime import datetime

import pytest

from tube_scout.models.parsed_title import ParsedTitle
from tube_scout.models.report import (
    ComplianceMatrix,
    DepartmentOverview,
    ProfessorDetail,
)
from tube_scout.models.video import Video
from tube_scout.reporting.department_report import DepartmentReportGenerator

# --- Fixtures ---


def _make_video(
    video_id: str,
    title: str,
    duration_seconds: int = 1800,
    view_count: int = 100,
    published_at: str = "2026-03-01T00:00:00",
) -> Video:
    """Helper to create a Video instance."""
    return Video(
        video_id=video_id,
        channel_id="UCtest123",
        title=title,
        published_at=datetime.fromisoformat(published_at),
        duration_seconds=duration_seconds,
        view_count=view_count,
    )


def _make_parsed(
    video_id: str,
    professor: list[str],
    course: str | None = None,
    year: int | None = 2026,
    semester: int | None = 1,
    week: int | None = None,
    session: int | None = None,
    parse_error: bool = False,
    category: str = "regular",
) -> ParsedTitle:
    """Helper to create a ParsedTitle instance."""
    return ParsedTitle(
        video_id=video_id,
        original_title=f"Test title {video_id}",
        professor=professor,
        course=course,
        year=year,
        semester=semester,
        week=week,
        session=session,
        parse_error=parse_error,
        category=category,
    )


@pytest.fixture
def sample_videos() -> list[Video]:
    """Sample video list for testing."""
    return [
        _make_video("v1", "Prof A Course 1 Week 1", 1800, 500),
        _make_video("v2", "Prof A Course 1 Week 2", 2400, 300),
        _make_video("v3", "Prof B Course 2 Week 1", 1200, 200),
        _make_video("v4", "Prof B Course 2 Week 2", 3600, 150),
        _make_video("v5", "Prof A Course 1 Week 3", 900, 400),
    ]


@pytest.fixture
def sample_parsed_titles() -> list[ParsedTitle]:
    """Sample parsed titles for testing."""
    return [
        _make_parsed("v1", ["ProfA"], "Course1", 2026, 1, week=1, session=1),
        _make_parsed("v2", ["ProfA"], "Course1", 2026, 1, week=2, session=1),
        _make_parsed("v3", ["ProfB"], "Course2", 2026, 1, week=1, session=1),
        _make_parsed("v4", ["ProfB"], "Course2", 2026, 1, week=2, session=1),
        _make_parsed("v5", ["ProfA"], "Course1", 2026, 1, week=3, session=1),
    ]


@pytest.fixture
def generator() -> DepartmentReportGenerator:
    """Create a DepartmentReportGenerator instance."""
    return DepartmentReportGenerator()


# --- T038: compute_overview tests ---


class TestComputeOverview:
    """Tests for DepartmentReportGenerator.compute_overview."""

    def test_total_videos(
        self,
        generator: DepartmentReportGenerator,
        sample_parsed_titles: list[ParsedTitle],
        sample_videos: list[Video],
    ) -> None:
        """Overview should count total videos."""
        overview = generator.compute_overview(
            sample_parsed_titles, sample_videos, "UCtest123",
        )
        assert isinstance(overview, DepartmentOverview)
        assert overview.total_videos == 5

    def test_total_professors(
        self,
        generator: DepartmentReportGenerator,
        sample_parsed_titles: list[ParsedTitle],
        sample_videos: list[Video],
    ) -> None:
        """Overview should count unique professors."""
        overview = generator.compute_overview(
            sample_parsed_titles, sample_videos, "UCtest123",
        )
        assert overview.total_professors == 2

    def test_total_courses(
        self,
        generator: DepartmentReportGenerator,
        sample_parsed_titles: list[ParsedTitle],
        sample_videos: list[Video],
    ) -> None:
        """Overview should count unique courses."""
        overview = generator.compute_overview(
            sample_parsed_titles, sample_videos, "UCtest123",
        )
        assert overview.total_courses == 2

    def test_total_duration_hours(
        self,
        generator: DepartmentReportGenerator,
        sample_parsed_titles: list[ParsedTitle],
        sample_videos: list[Video],
    ) -> None:
        """Overview should calculate total duration in hours."""
        overview = generator.compute_overview(
            sample_parsed_titles, sample_videos, "UCtest123",
        )
        # 1800+2400+1200+3600+900 = 9900 seconds = 2.75 hours
        assert overview.total_duration_hours == pytest.approx(2.75, abs=0.01)

    def test_total_views(
        self,
        generator: DepartmentReportGenerator,
        sample_parsed_titles: list[ParsedTitle],
        sample_videos: list[Video],
    ) -> None:
        """Overview should sum all views."""
        overview = generator.compute_overview(
            sample_parsed_titles, sample_videos, "UCtest123",
        )
        assert overview.total_views == 1550

    def test_parse_success_rate(
        self,
        generator: DepartmentReportGenerator,
        sample_videos: list[Video],
    ) -> None:
        """Overview should calculate parse success rate."""
        parsed = [
            _make_parsed("v1", ["ProfA"], "Course1", 2026, 1, week=1),
            _make_parsed("v2", ["ProfA"], "Course1", 2026, 1, week=2),
            _make_parsed("v3", ["ProfB"], parse_error=True),
        ]
        overview = generator.compute_overview(
            parsed, sample_videos[:3], "UCtest123",
        )
        # 2 out of 3 parsed successfully
        assert overview.parse_success_rate == pytest.approx(2 / 3, abs=0.01)

    def test_empty_input(
        self,
        generator: DepartmentReportGenerator,
    ) -> None:
        """Overview should handle empty inputs gracefully."""
        overview = generator.compute_overview([], [], "UCtest123")
        assert overview.total_videos == 0
        assert overview.total_professors == 0
        assert overview.total_courses == 0
        assert overview.total_duration_hours == 0.0
        assert overview.total_views == 0
        assert overview.parse_success_rate == 0.0

    def test_channel_id_in_overview(
        self,
        generator: DepartmentReportGenerator,
        sample_parsed_titles: list[ParsedTitle],
        sample_videos: list[Video],
    ) -> None:
        """Overview should include the channel_id."""
        overview = generator.compute_overview(
            sample_parsed_titles, sample_videos, "UCtest123",
        )
        assert overview.channel_id == "UCtest123"


# --- T038: compute_professor_details tests ---


class TestComputeProfessorDetails:
    """Tests for DepartmentReportGenerator.compute_professor_details."""

    def test_returns_professor_list(
        self,
        generator: DepartmentReportGenerator,
        sample_parsed_titles: list[ParsedTitle],
        sample_videos: list[Video],
    ) -> None:
        """Should return a list of ProfessorDetail."""
        details = generator.compute_professor_details(
            sample_parsed_titles, sample_videos,
        )
        assert len(details) == 2
        assert all(isinstance(d, ProfessorDetail) for d in details)

    def test_video_count(
        self,
        generator: DepartmentReportGenerator,
        sample_parsed_titles: list[ParsedTitle],
        sample_videos: list[Video],
    ) -> None:
        """Each professor should have correct video count."""
        details = generator.compute_professor_details(
            sample_parsed_titles, sample_videos,
        )
        by_name = {d.professor_name: d for d in details}
        assert by_name["ProfA"].video_count == 3
        assert by_name["ProfB"].video_count == 2

    def test_courses_list(
        self,
        generator: DepartmentReportGenerator,
        sample_parsed_titles: list[ParsedTitle],
        sample_videos: list[Video],
    ) -> None:
        """Each professor should have unique courses listed."""
        details = generator.compute_professor_details(
            sample_parsed_titles, sample_videos,
        )
        by_name = {d.professor_name: d for d in details}
        assert by_name["ProfA"].courses == ["Course1"]
        assert by_name["ProfB"].courses == ["Course2"]

    def test_weekly_coverage(
        self,
        generator: DepartmentReportGenerator,
        sample_parsed_titles: list[ParsedTitle],
        sample_videos: list[Video],
    ) -> None:
        """Weekly coverage = weeks with uploads / 16."""
        details = generator.compute_professor_details(
            sample_parsed_titles, sample_videos,
        )
        by_name = {d.professor_name: d for d in details}
        # ProfA has weeks 1, 2, 3 -> 3/16
        assert by_name["ProfA"].weekly_coverage == pytest.approx(3 / 16, abs=0.01)
        # ProfB has weeks 1, 2 -> 2/16
        assert by_name["ProfB"].weekly_coverage == pytest.approx(2 / 16, abs=0.01)

    def test_avg_duration_minutes(
        self,
        generator: DepartmentReportGenerator,
        sample_parsed_titles: list[ParsedTitle],
        sample_videos: list[Video],
    ) -> None:
        """Average duration should be computed in minutes."""
        details = generator.compute_professor_details(
            sample_parsed_titles, sample_videos,
        )
        by_name = {d.professor_name: d for d in details}
        # ProfA: v1=1800, v2=2400, v5=900 -> avg=1700 sec -> 28.33 min
        assert by_name["ProfA"].avg_duration_minutes == pytest.approx(
            1700 / 60, abs=0.1,
        )

    def test_total_and_avg_views(
        self,
        generator: DepartmentReportGenerator,
        sample_parsed_titles: list[ParsedTitle],
        sample_videos: list[Video],
    ) -> None:
        """Total and average views should be correct."""
        details = generator.compute_professor_details(
            sample_parsed_titles, sample_videos,
        )
        by_name = {d.professor_name: d for d in details}
        # ProfA: v1=500, v2=300, v5=400 -> total=1200, avg=400
        assert by_name["ProfA"].total_views == 1200
        assert by_name["ProfA"].avg_views == pytest.approx(400.0, abs=0.1)

    def test_session_completeness(
        self,
        generator: DepartmentReportGenerator,
        sample_videos: list[Video],
    ) -> None:
        """Session completeness: avg sessions per week / expected."""
        parsed = [
            _make_parsed("v1", ["ProfA"], "C1", 2026, 1, week=1, session=1),
            _make_parsed("v2", ["ProfA"], "C1", 2026, 1, week=1, session=2),
            _make_parsed("v3", ["ProfA"], "C1", 2026, 1, week=2, session=1),
        ]
        details = generator.compute_professor_details(parsed, sample_videos[:3])
        by_name = {d.professor_name: d for d in details}
        # Week 1: 2 sessions, week 2: 1 session. Max sessions seen = 2.
        # Completeness = avg(2/2, 1/2) = avg(1.0, 0.5) = 0.75
        assert by_name["ProfA"].session_completeness == pytest.approx(0.75, abs=0.01)

    def test_empty_input(
        self,
        generator: DepartmentReportGenerator,
    ) -> None:
        """Should handle empty input gracefully."""
        details = generator.compute_professor_details([], [])
        assert details == []

    def test_multi_professor_video(
        self,
        generator: DepartmentReportGenerator,
    ) -> None:
        """A video with multiple professors should count for each."""
        parsed = [
            _make_parsed("v1", ["ProfA", "ProfB"], "C1", 2026, 1, week=1, session=1),
        ]
        videos = [_make_video("v1", "Co-taught", 1800, 100)]
        details = generator.compute_professor_details(parsed, videos)
        assert len(details) == 2
        for d in details:
            assert d.video_count == 1


# --- T038: compute_compliance tests ---


class TestComputeCompliance:
    """Tests for DepartmentReportGenerator.compute_compliance."""

    def test_returns_compliance_list(
        self,
        generator: DepartmentReportGenerator,
        sample_parsed_titles: list[ParsedTitle],
        sample_videos: list[Video],
    ) -> None:
        """Should return a list of ComplianceMatrix entries."""
        compliance = generator.compute_compliance(
            sample_parsed_titles, sample_videos,
        )
        assert len(compliance) == 2
        assert all(isinstance(c, ComplianceMatrix) for c in compliance)

    def test_uploaded_weeks(
        self,
        generator: DepartmentReportGenerator,
        sample_parsed_titles: list[ParsedTitle],
        sample_videos: list[Video],
    ) -> None:
        """Weeks with uploads should be marked 'uploaded'."""
        compliance = generator.compute_compliance(
            sample_parsed_titles, sample_videos,
        )
        by_name = {c.professor_name: c for c in compliance}
        assert by_name["ProfA"].week_statuses[1] == "uploaded"
        assert by_name["ProfA"].week_statuses[2] == "uploaded"
        assert by_name["ProfA"].week_statuses[3] == "uploaded"

    def test_missing_weeks(
        self,
        generator: DepartmentReportGenerator,
        sample_parsed_titles: list[ParsedTitle],
        sample_videos: list[Video],
    ) -> None:
        """Weeks without uploads should be marked 'missing'."""
        compliance = generator.compute_compliance(
            sample_parsed_titles, sample_videos,
        )
        by_name = {c.professor_name: c for c in compliance}
        # ProfA has weeks 1,2,3 but not 4-16
        assert by_name["ProfA"].week_statuses[4] == "missing"
        assert by_name["ProfA"].week_statuses[16] == "missing"

    def test_late_upload_with_calendar(
        self,
        generator: DepartmentReportGenerator,
    ) -> None:
        """Uploads after week start date should be marked 'late'."""
        # Calendar: week 1 starts 2026-03-02
        calendar = {1: "2026-03-02", 2: "2026-03-09"}
        parsed = [
            _make_parsed("v1", ["ProfA"], "C1", 2026, 1, week=1, session=1),
        ]
        # Video uploaded on 2026-03-05 (3 days after week 1 start)
        videos = [
            _make_video("v1", "Late upload", 1800, 100, "2026-03-05T00:00:00"),
        ]
        compliance = generator.compute_compliance(parsed, videos, calendar)
        by_name = {c.professor_name: c for c in compliance}
        assert by_name["ProfA"].week_statuses[1] == "late"

    def test_on_time_upload_with_calendar(
        self,
        generator: DepartmentReportGenerator,
    ) -> None:
        """Uploads before or on week start date should be 'uploaded'."""
        calendar = {1: "2026-03-02", 2: "2026-03-09"}
        parsed = [
            _make_parsed("v1", ["ProfA"], "C1", 2026, 1, week=1, session=1),
        ]
        videos = [
            _make_video("v1", "On time", 1800, 100, "2026-03-01T00:00:00"),
        ]
        compliance = generator.compute_compliance(parsed, videos, calendar)
        by_name = {c.professor_name: c for c in compliance}
        assert by_name["ProfA"].week_statuses[1] == "uploaded"

    def test_no_calendar_skips_late_detection(
        self,
        generator: DepartmentReportGenerator,
    ) -> None:
        """Without calendar, uploads are just 'uploaded' (no 'late')."""
        parsed = [
            _make_parsed("v1", ["ProfA"], "C1", 2026, 1, week=1, session=1),
        ]
        videos = [_make_video("v1", "No calendar", 1800, 100)]
        compliance = generator.compute_compliance(parsed, videos)
        by_name = {c.professor_name: c for c in compliance}
        assert by_name["ProfA"].week_statuses[1] == "uploaded"

    def test_upload_deadline_compliance_rate(
        self,
        generator: DepartmentReportGenerator,
    ) -> None:
        """upload_deadline_compliance should reflect on-time uploads."""
        calendar = {1: "2026-03-02", 2: "2026-03-09"}
        parsed = [
            _make_parsed("v1", ["ProfA"], "C1", 2026, 1, week=1, session=1),
            _make_parsed("v2", ["ProfA"], "C1", 2026, 1, week=2, session=1),
        ]
        videos = [
            _make_video("v1", "On time", 1800, 100, "2026-03-01T00:00:00"),
            _make_video("v2", "Late", 1800, 100, "2026-03-12T00:00:00"),
        ]
        compliance = generator.compute_compliance(parsed, videos, calendar)
        by_name = {c.professor_name: c for c in compliance}
        # 1 on-time out of 2 uploaded = 0.5
        assert by_name["ProfA"].upload_deadline_compliance == pytest.approx(
            0.5, abs=0.01,
        )

    def test_empty_input(
        self,
        generator: DepartmentReportGenerator,
    ) -> None:
        """Should handle empty input gracefully."""
        compliance = generator.compute_compliance([], [])
        assert compliance == []


# --- T046: Year/semester scoping tests ---


class TestYearSemesterScoping:
    """Tests for year/semester filtering before computing."""

    def test_filter_by_year(
        self,
        generator: DepartmentReportGenerator,
    ) -> None:
        """Should filter parsed titles by year."""
        parsed = [
            _make_parsed("v1", ["ProfA"], "C1", 2025, 1, week=1),
            _make_parsed("v2", ["ProfA"], "C1", 2026, 1, week=1),
        ]
        videos = [
            _make_video("v1", "2025", 1800, 100),
            _make_video("v2", "2026", 1800, 200),
        ]
        overview = generator.compute_overview(
            parsed, videos, "UCtest123", year=2026,
        )
        assert overview.total_videos == 1
        assert overview.total_views == 200
        assert overview.year == 2026

    def test_filter_by_semester(
        self,
        generator: DepartmentReportGenerator,
    ) -> None:
        """Should filter parsed titles by semester."""
        parsed = [
            _make_parsed("v1", ["ProfA"], "C1", 2026, 1, week=1),
            _make_parsed("v2", ["ProfA"], "C1", 2026, 2, week=1),
        ]
        videos = [
            _make_video("v1", "Sem1", 1800, 100),
            _make_video("v2", "Sem2", 1800, 200),
        ]
        overview = generator.compute_overview(
            parsed, videos, "UCtest123", semester=1,
        )
        assert overview.total_videos == 1
        assert overview.total_views == 100
        assert overview.semester == 1

    def test_filter_by_year_and_semester(
        self,
        generator: DepartmentReportGenerator,
    ) -> None:
        """Should filter by both year and semester."""
        parsed = [
            _make_parsed("v1", ["ProfA"], "C1", 2025, 1, week=1),
            _make_parsed("v2", ["ProfA"], "C1", 2026, 1, week=1),
            _make_parsed("v3", ["ProfA"], "C1", 2026, 2, week=1),
        ]
        videos = [
            _make_video("v1", "2025-1", 1800, 100),
            _make_video("v2", "2026-1", 1800, 200),
            _make_video("v3", "2026-2", 1800, 300),
        ]
        overview = generator.compute_overview(
            parsed, videos, "UCtest123", year=2026, semester=1,
        )
        assert overview.total_videos == 1
        assert overview.total_views == 200

    def test_scoping_applies_to_professor_details(
        self,
        generator: DepartmentReportGenerator,
    ) -> None:
        """Year/semester filter should also apply to professor details."""
        parsed = [
            _make_parsed("v1", ["ProfA"], "C1", 2026, 1, week=1),
            _make_parsed("v2", ["ProfB"], "C2", 2025, 1, week=1),
        ]
        videos = [
            _make_video("v1", "2026", 1800, 100),
            _make_video("v2", "2025", 1800, 200),
        ]
        details = generator.compute_professor_details(
            parsed, videos, year=2026,
        )
        assert len(details) == 1
        assert details[0].professor_name == "ProfA"

    def test_scoping_applies_to_compliance(
        self,
        generator: DepartmentReportGenerator,
    ) -> None:
        """Year/semester filter should also apply to compliance."""
        parsed = [
            _make_parsed("v1", ["ProfA"], "C1", 2026, 1, week=1),
            _make_parsed("v2", ["ProfB"], "C2", 2025, 1, week=1),
        ]
        videos = [
            _make_video("v1", "2026", 1800, 100),
            _make_video("v2", "2025", 1800, 200),
        ]
        compliance = generator.compute_compliance(
            parsed, videos, year=2026,
        )
        assert len(compliance) == 1
        assert compliance[0].professor_name == "ProfA"
