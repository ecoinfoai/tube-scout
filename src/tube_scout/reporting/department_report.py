"""Department report generator (US4 — FR-015~FR-019)."""

from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader

from tube_scout.models.parsed_title import ParsedTitle
from tube_scout.models.report import (
    ComplianceMatrix,
    DepartmentOverview,
    ProfessorDetail,
)
from tube_scout.models.video import Video


class DepartmentReportGenerator:
    """Generate department-level reports.

    Includes overview, professor detail, and compliance.

    Args:
        templates_dir: Optional custom templates directory.
    """

    def __init__(self, templates_dir: Path | None = None) -> None:
        if templates_dir is None:
            templates_dir = Path(__file__).parent / "templates"
        self._env = Environment(
            loader=FileSystemLoader(str(templates_dir)),
            autoescape=True,
        )

    def _filter_by_scope(
        self,
        parsed_titles: list[ParsedTitle],
        videos: list[Video],
        year: int | None = None,
        semester: int | None = None,
    ) -> tuple[list[ParsedTitle], list[Video]]:
        """Filter parsed titles and videos by year/semester scope.

        Args:
            parsed_titles: All parsed titles.
            videos: All videos.
            year: Filter by academic year.
            semester: Filter by semester.

        Returns:
            Tuple of filtered (parsed_titles, videos).
        """
        filtered_parsed = parsed_titles
        if year is not None:
            filtered_parsed = [p for p in filtered_parsed if p.year == year]
        if semester is not None:
            filtered_parsed = [p for p in filtered_parsed if p.semester == semester]

        filtered_video_ids = {p.video_id for p in filtered_parsed}
        filtered_videos = [v for v in videos if v.video_id in filtered_video_ids]
        return filtered_parsed, filtered_videos

    def compute_overview(
        self,
        parsed_titles: list[ParsedTitle],
        videos: list[Video],
        channel_id: str,
        channel_name: str = "",
        year: int | None = None,
        semester: int | None = None,
    ) -> DepartmentOverview:
        """Compute department overview metrics.

        Args:
            parsed_titles: Parsed video titles.
            videos: Video metadata list.
            channel_id: YouTube channel ID.
            channel_name: Channel display name.
            year: Optional year filter.
            semester: Optional semester filter.

        Returns:
            DepartmentOverview with computed metrics.
        """
        filtered_parsed, filtered_videos = self._filter_by_scope(
            parsed_titles,
            videos,
            year,
            semester,
        )

        video_map = {v.video_id: v for v in filtered_videos}

        professors: set[str] = set()
        courses: set[str] = set()
        for pt in filtered_parsed:
            for prof in pt.professor:
                professors.add(prof)
            if pt.course:
                courses.add(pt.course)

        total_duration_seconds = sum(
            video_map[pt.video_id].duration_seconds
            for pt in filtered_parsed
            if pt.video_id in video_map
        )
        total_views = sum(
            video_map[pt.video_id].view_count
            for pt in filtered_parsed
            if pt.video_id in video_map
        )

        parse_success_count = sum(1 for pt in filtered_parsed if not pt.parse_error)
        parse_success_rate = (
            parse_success_count / len(filtered_parsed) if filtered_parsed else 0.0
        )

        return DepartmentOverview(
            channel_id=channel_id,
            channel_name=channel_name,
            year=year,
            semester=semester,
            total_videos=len(filtered_parsed),
            total_professors=len(professors),
            total_courses=len(courses),
            total_duration_hours=total_duration_seconds / 3600,
            total_views=total_views,
            parse_success_rate=parse_success_rate,
        )

    def compute_professor_details(
        self,
        parsed_titles: list[ParsedTitle],
        videos: list[Video],
        year: int | None = None,
        semester: int | None = None,
    ) -> list[ProfessorDetail]:
        """Compute per-professor detail metrics.

        Args:
            parsed_titles: Parsed video titles.
            videos: Video metadata list.
            year: Optional year filter.
            semester: Optional semester filter.

        Returns:
            List of ProfessorDetail, one per professor.
        """
        filtered_parsed, filtered_videos = self._filter_by_scope(
            parsed_titles,
            videos,
            year,
            semester,
        )

        if not filtered_parsed:
            return []

        video_map = {v.video_id: v for v in filtered_videos}

        # Group by professor
        prof_titles: dict[str, list[ParsedTitle]] = defaultdict(list)
        for pt in filtered_parsed:
            for prof in pt.professor:
                prof_titles[prof].append(pt)

        results: list[ProfessorDetail] = []
        for prof_name, titles in sorted(prof_titles.items()):
            video_ids = [pt.video_id for pt in titles]
            prof_videos = [video_map[vid] for vid in video_ids if vid in video_map]

            courses = sorted({pt.course for pt in titles if pt.course})

            # Weekly coverage: unique weeks / 16
            weeks_with_uploads = {pt.week for pt in titles if pt.week is not None}
            weekly_coverage = len(weeks_with_uploads) / 16

            # Session completeness
            session_completeness = self._compute_session_completeness(titles)

            total_duration = sum(v.duration_seconds for v in prof_videos)
            avg_duration_min = (
                (total_duration / len(prof_videos) / 60) if prof_videos else 0.0
            )

            total_views = sum(v.view_count for v in prof_videos)
            avg_views = total_views / len(prof_videos) if prof_videos else 0.0

            results.append(
                ProfessorDetail(
                    professor_name=prof_name,
                    video_count=len(titles),
                    courses=courses,
                    weekly_coverage=weekly_coverage,
                    session_completeness=session_completeness,
                    avg_duration_minutes=avg_duration_min,
                    total_views=total_views,
                    avg_views=avg_views,
                    validation_error_count=0,
                )
            )

        return results

    def _compute_session_completeness(
        self,
        titles: list[ParsedTitle],
    ) -> float:
        """Compute session completeness for a professor's titles.

        Args:
            titles: Parsed titles for one professor.

        Returns:
            Session completeness ratio (0.0-1.0).
        """
        # Group sessions by week
        week_sessions: dict[int, set[int]] = defaultdict(set)
        for pt in titles:
            if pt.week is not None and pt.session is not None:
                week_sessions[pt.week].add(pt.session)

        if not week_sessions:
            return 0.0

        # Expected sessions = max sessions seen across all weeks
        max_sessions = max(len(sessions) for sessions in week_sessions.values())
        if max_sessions == 0:
            return 0.0

        # Average completeness across weeks
        completeness_per_week = [
            len(sessions) / max_sessions for sessions in week_sessions.values()
        ]
        return sum(completeness_per_week) / len(completeness_per_week)

    def compute_compliance(
        self,
        parsed_titles: list[ParsedTitle],
        videos: list[Video],
        calendar: dict[int, str] | None = None,
        year: int | None = None,
        semester: int | None = None,
    ) -> list[ComplianceMatrix]:
        """Compute compliance matrix (professor x week status).

        Args:
            parsed_titles: Parsed video titles.
            videos: Video metadata list.
            calendar: Optional dict mapping week number to start date (ISO format).
            year: Optional year filter.
            semester: Optional semester filter.

        Returns:
            List of ComplianceMatrix, one per professor.
        """
        filtered_parsed, filtered_videos = self._filter_by_scope(
            parsed_titles,
            videos,
            year,
            semester,
        )

        if not filtered_parsed:
            return []

        video_map = {v.video_id: v for v in filtered_videos}

        # Group by professor
        prof_titles: dict[str, list[ParsedTitle]] = defaultdict(list)
        for pt in filtered_parsed:
            for prof in pt.professor:
                prof_titles[prof].append(pt)

        results: list[ComplianceMatrix] = []
        for prof_name, titles in sorted(prof_titles.items()):
            week_statuses: dict[int, str] = {}
            on_time_count = 0
            uploaded_count = 0

            # Track which weeks have uploads
            week_video_ids: dict[int, list[str]] = defaultdict(list)
            for pt in titles:
                if pt.week is not None:
                    week_video_ids[pt.week].append(pt.video_id)

            # Fill all 16 weeks
            for week in range(1, 17):
                if week in week_video_ids:
                    # Check if late (only if calendar provided)
                    is_late = False
                    if calendar and week in calendar:
                        week_start = datetime.fromisoformat(calendar[week])
                        for vid in week_video_ids[week]:
                            if vid in video_map:
                                pub_date = video_map[vid].published_at
                                # Compare dates (strip timezone if needed)
                                pub_naive = pub_date.replace(tzinfo=None)
                                if pub_naive > week_start:
                                    is_late = True
                                    break

                    if is_late:
                        week_statuses[week] = "late"
                    else:
                        week_statuses[week] = "uploaded"
                        on_time_count += 1
                    uploaded_count += 1
                else:
                    week_statuses[week] = "missing"

            compliance_rate = (
                on_time_count / uploaded_count if uploaded_count > 0 else 0.0
            )

            results.append(
                ComplianceMatrix(
                    professor_name=prof_name,
                    week_statuses=week_statuses,
                    upload_deadline_compliance=compliance_rate,
                )
            )

        return results

    def generate_html(
        self,
        overview: DepartmentOverview,
        professor_details: list[ProfessorDetail],
        compliance_entries: list[ComplianceMatrix],
        output_path: Path,
        validation_findings: list[Any] | None = None,
    ) -> Path:
        """Generate an HTML department report.

        Args:
            overview: Department overview metrics.
            professor_details: Per-professor details.
            compliance_entries: Compliance matrix entries.
            output_path: Path to write the HTML file.
            validation_findings: Optional validation findings.

        Returns:
            Path to the generated HTML file.
        """
        import plotly.graph_objects as go

        # Build compliance heatmap
        heatmap_html = ""
        if compliance_entries:
            professors = [c.professor_name for c in compliance_entries]
            weeks = list(range(1, 17))
            status_to_value = {"uploaded": 1, "late": 0.5, "missing": 0}

            z_data = []
            text_data = []
            for entry in compliance_entries:
                row_values = []
                row_text = []
                for week in weeks:
                    status = entry.week_statuses.get(week, "missing")
                    row_values.append(status_to_value.get(status, 0))
                    row_text.append(status)
                z_data.append(row_values)
                text_data.append(row_text)

            colorscale = [
                [0, "#dc3545"],  # red = missing
                [0.5, "#ffc107"],  # yellow = late
                [1, "#28a745"],  # green = uploaded
            ]

            fig = go.Figure(
                data=go.Heatmap(
                    z=z_data,
                    x=[f"W{w}" for w in weeks],
                    y=professors,
                    text=text_data,
                    texttemplate="%{text}",
                    colorscale=colorscale,
                    showscale=False,
                )
            )
            fig.update_layout(
                title="Upload Compliance Heatmap",
                xaxis_title="Week",
                yaxis_title="Professor",
                height=max(300, len(professors) * 40 + 100),
            )
            heatmap_html = fig.to_html(full_html=False, include_plotlyjs="cdn")

        template = self._env.get_template("department.html")
        html = template.render(
            overview=overview,
            professor_details=professor_details,
            compliance_entries=compliance_entries,
            heatmap_html=heatmap_html,
            validation_findings=validation_findings or [],
            generated_at=datetime.now().isoformat(),
        )

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(html, encoding="utf-8")
        return output_path

    def generate_pdf(self, html_path: Path) -> Path | None:
        """Generate a PDF from an HTML report via weasyprint.

        Args:
            html_path: Path to the HTML file.

        Returns:
            Path to the generated PDF file, or None if weasyprint is not installed.
        """
        try:
            from weasyprint import HTML
        except ImportError:
            return None

        pdf_path = html_path.with_suffix(".pdf")
        HTML(filename=str(html_path)).write_pdf(str(pdf_path))
        return pdf_path
