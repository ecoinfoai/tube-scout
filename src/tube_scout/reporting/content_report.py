"""Content quality report generator.

Generates HTML, Excel, and JSON reports from comparison results
and quality check data for administrator review.
"""

import json
from collections import Counter
from pathlib import Path
from typing import Any

import openpyxl
from openpyxl.styles import Font, PatternFill


def _sanitize_cell(value: Any) -> Any:
    """Sanitize a cell value to prevent Excel formula injection.

    Args:
        value: Cell value to sanitize.

    Returns:
        Sanitized value safe for Excel.
    """
    if not isinstance(value, str):
        return value
    if value and value[0] in ("=", "+", "-", "@"):
        return "'" + value
    return value


def _build_summary(comparisons: list[dict[str, Any]]) -> dict[str, Any]:
    """Build summary statistics from comparison results.

    Args:
        comparisons: List of comparison result dicts.

    Returns:
        Summary dict with counts and statistics.
    """
    grade_counts = Counter(c.get("grade", "unknown") for c in comparisons)
    review_counts = Counter(c.get("review_status", "UNREVIEWED") for c in comparisons)

    # Per-professor suspicion rates
    professor_scores: dict[str, list[float]] = {}
    for c in comparisons:
        prof = c.get("professor", "Unknown")
        score = c.get("suspicion_score", 0.0) or 0.0
        professor_scores.setdefault(prof, []).append(score)

    professor_rates = {
        prof: round(sum(scores) / len(scores), 2)
        for prof, scores in professor_scores.items()
    }

    return {
        "total_comparisons": len(comparisons),
        "grade_counts": {
            "critical": grade_counts.get("critical", 0),
            "high": grade_counts.get("high", 0),
            "moderate": grade_counts.get("moderate", 0),
            "normal": grade_counts.get("normal", 0),
        },
        "review_counts": dict(review_counts),
        "professor_avg_suspicion": professor_rates,
    }


class ContentReportGenerator:
    """Generator for content quality reports in multiple formats."""

    def generate_json(
        self,
        comparisons: list[dict[str, Any]],
        quality_results: list[dict[str, Any]],
        output_path: Path,
    ) -> None:
        """Generate JSON report.

        Args:
            comparisons: Comparison result dicts.
            quality_results: Quality check result dicts.
            output_path: Output file path.
        """
        report = {
            "summary": _build_summary(comparisons),
            "comparisons": comparisons,
            "quality_results": quality_results,
        }
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )

    def generate_html(
        self,
        comparisons: list[dict[str, Any]],
        quality_results: list[dict[str, Any]],
        output_path: Path,
    ) -> None:
        """Generate HTML report.

        Args:
            comparisons: Comparison result dicts.
            quality_results: Quality check result dicts.
            output_path: Output file path.
        """
        summary = _build_summary(comparisons)

        grade_colors = {
            "critical": "#dc3545",
            "high": "#fd7e14",
            "moderate": "#ffc107",
            "normal": "#28a745",
        }

        # Build comparison rows
        rows_html = ""
        sorted_comps = sorted(
            comparisons,
            key=lambda x: x.get("suspicion_score", 0),
            reverse=True,
        )
        for c in sorted_comps:
            grade = c.get("grade", "")
            color = grade_colors.get(grade, "#6c757d")
            prof = c.get("professor", "")
            course = c.get("course", "")
            ws = f"W{c.get('week', '?')}/S{c.get('session', '?')}"
            yrs = f"{c.get('year_from', '')}->{c.get('year_to', '')}"
            score = c.get("suspicion_score", 0)
            status = c.get("review_status", "")
            rows_html += f"""
            <tr>
                <td>{prof}</td>
                <td>{course}</td>
                <td>{ws}</td>
                <td>{yrs}</td>
                <td style="color: {color}; font-weight: bold;">{score:.1f}</td>
                <td style="color: {color};">{grade}</td>
                <td>{status}</td>
            </tr>"""

        # Build quality rows
        quality_html = ""
        for q in quality_results:
            quality_html += f"""
            <tr>
                <td>{q.get('video_id', '')}</td>
                <td>{'Pass' if q.get('q001_voice_present') else 'Fail'}</td>
                <td>{'Pass' if q.get('q002_min_duration') else 'Fail'}</td>
                <td>{q.get('q003_course_relevance', 'N/A')}</td>
                <td>{q.get('q004_silence_ratio', 'N/A')}</td>
                <td>{q.get('q005_speech_density', 'N/A')}</td>
                <td>{q.get('pass_count', 0)}/5</td>
            </tr>"""

        gc = summary["grade_counts"]
        cnt_crit = gc["critical"]
        cnt_high = gc["high"]
        cnt_mod = gc["moderate"]
        cnt_norm = gc["normal"]

        html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="utf-8">
    <title>Content Quality Report</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont,
                'Segoe UI', sans-serif;
            margin: 20px;
        }}
        h1 {{ color: #333; }}
        h2 {{ color: #555; margin-top: 30px; }}
        table {{
            border-collapse: collapse;
            width: 100%;
            margin-top: 10px;
        }}
        th, td {{
            border: 1px solid #ddd;
            padding: 8px;
            text-align: left;
        }}
        th {{ background-color: #f8f9fa; font-weight: bold; }}
        tr:nth-child(even) {{ background-color: #f2f2f2; }}
        .summary {{
            display: flex; gap: 20px; margin: 20px 0;
        }}
        .summary-card {{
            padding: 15px;
            border-radius: 8px;
            min-width: 120px;
            text-align: center;
        }}
        .critical {{ background-color: #f8d7da; color: #721c24; }}
        .high {{ background-color: #fff3cd; color: #856404; }}
        .moderate {{ background-color: #d1ecf1; color: #0c5460; }}
        .normal {{ background-color: #d4edda; color: #155724; }}
    </style>
</head>
<body>
    <h1>Content Quality Report</h1>

    <h2>Summary</h2>
    <div class="summary">
        <div class="summary-card critical">
            <div style="font-size: 24px; font-weight: bold;">{cnt_crit}</div>
            <div>Critical</div>
        </div>
        <div class="summary-card high">
            <div style="font-size: 24px; font-weight: bold;">{cnt_high}</div>
            <div>High</div>
        </div>
        <div class="summary-card moderate">
            <div style="font-size: 24px; font-weight: bold;">{cnt_mod}</div>
            <div>Moderate</div>
        </div>
        <div class="summary-card normal">
            <div style="font-size: 24px; font-weight: bold;">{cnt_norm}</div>
            <div>Normal</div>
        </div>
    </div>

    <h2>Suspicion Results</h2>
    <table>
        <thead>
            <tr>
                <th>Professor</th>
                <th>Course</th>
                <th>Week/Session</th>
                <th>Years</th>
                <th>Score</th>
                <th>Grade</th>
                <th>Review Status</th>
            </tr>
        </thead>
        <tbody>{rows_html}
        </tbody>
    </table>

    <h2>Quality Checklist</h2>
    <table>
        <thead>
            <tr>
                <th>Video ID</th>
                <th>Q-001 Voice</th>
                <th>Q-002 Duration</th>
                <th>Q-003 Relevance</th>
                <th>Q-004 Silence</th>
                <th>Q-005 Density</th>
                <th>Pass</th>
            </tr>
        </thead>
        <tbody>{quality_html}
        </tbody>
    </table>
</body>
</html>"""

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(html, encoding="utf-8")

    def generate_xlsx(
        self,
        comparisons: list[dict[str, Any]],
        quality_results: list[dict[str, Any]],
        output_path: Path,
    ) -> None:
        """Generate Excel report with multiple sheets.

        Args:
            comparisons: Comparison result dicts.
            quality_results: Quality check result dicts.
            output_path: Output file path.
        """
        wb = openpyxl.Workbook()
        header_font = Font(bold=True)

        # Sheet 1: Suspicion Summary
        ws_susp = wb.active
        ws_susp.title = "Suspicion Summary"
        headers = [
            "ID", "Professor", "Course", "Week", "Session",
            "Year From", "Year To", "Hash Match", "Cosine Sim",
            "Change Rate", "New Terms", "Duration Diff",
            "Score", "Grade", "Review Status",
        ]
        for col, h in enumerate(headers, 1):
            cell = ws_susp.cell(row=1, column=col, value=h)
            cell.font = header_font

        grade_fills = {
            "critical": PatternFill(
                start_color="DC3545", end_color="DC3545",
                fill_type="solid",
            ),
            "high": PatternFill(
                start_color="FD7E14", end_color="FD7E14",
                fill_type="solid",
            ),
            "moderate": PatternFill(
                start_color="FFC107", end_color="FFC107",
                fill_type="solid",
            ),
            "normal": PatternFill(
                start_color="28A745", end_color="28A745",
                fill_type="solid",
            ),
        }

        sorted_comps = sorted(
            comparisons,
            key=lambda x: x.get("suspicion_score", 0),
            reverse=True,
        )
        for row_idx, c in enumerate(sorted_comps, start=2):
            values = [
                c.get("id"),
                _sanitize_cell(c.get("professor", "")),
                _sanitize_cell(c.get("course", "")),
                c.get("week"),
                c.get("session"),
                c.get("year_from"),
                c.get("year_to"),
                bool(c.get("i1_hash_match")),
                c.get("i2_cosine_similarity"),
                c.get("i3_change_rate"),
                c.get("i4_new_term_count"),
                c.get("i5_duration_diff_seconds"),
                c.get("suspicion_score"),
                c.get("grade", ""),
                c.get("review_status", ""),
            ]
            for col, val in enumerate(values, 1):
                ws_susp.cell(row=row_idx, column=col, value=val)

            grade = c.get("grade", "")
            if grade in grade_fills:
                ws_susp.cell(row=row_idx, column=14).fill = grade_fills[grade]

        # Sheet 2: Quality Results
        ws_qual = wb.create_sheet("Quality Results")
        q_headers = [
            "Video ID", "Q-001 Voice", "Q-002 Duration",
            "Q-003 Relevance", "Q-004 Silence", "Q-005 Density", "Pass Count",
        ]
        for col, h in enumerate(q_headers, 1):
            cell = ws_qual.cell(row=1, column=col, value=h)
            cell.font = header_font

        for row_idx, q in enumerate(quality_results, start=2):
            values = [
                _sanitize_cell(q.get("video_id", "")),
                bool(q.get("q001_voice_present")),
                bool(q.get("q002_min_duration")),
                q.get("q003_course_relevance"),
                q.get("q004_silence_ratio"),
                q.get("q005_speech_density"),
                q.get("pass_count", 0),
            ]
            for col, val in enumerate(values, 1):
                ws_qual.cell(row=row_idx, column=col, value=val)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        wb.save(str(output_path))
        wb.close()
