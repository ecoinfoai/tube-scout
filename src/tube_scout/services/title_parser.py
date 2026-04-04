"""Video title parser for Korean university lecture videos."""

import json
import re
from dataclasses import dataclass
from pathlib import Path

from tube_scout.models.parsed_title import ParsedTitle

SUPPLEMENTARY_KEYWORDS = frozenset(
    {"핵심영상", "보완영상", "질문응답", "보충", "특강", "OT"}
)


@dataclass(frozen=True)
class TitlePattern:
    """A regex pattern for title parsing.

    Args:
        name: Pattern identifier.
        pattern: Compiled regex with named groups.
        priority: Lower number means tried first.
        description: Human-readable pattern description.
    """

    name: str
    pattern: re.Pattern[str]
    priority: int
    description: str


def _build_patterns() -> list[TitlePattern]:
    """Build the priority-ordered list of title patterns.

    Returns:
        List of TitlePattern sorted by priority (lowest first).
    """
    patterns = [
        TitlePattern(
            name="semester_explicit",
            pattern=re.compile(
                r"^(?P<course>\S+)\s+(?P<year>\d{4})\s+"
                r"(?P<semester>[12])학기\s+"
                r"(?P<professor>[가-힣]{2,4}(?:/[가-힣]{2,4})*)\s+"
                r"(?P<week>\d+)주차\s+(?P<session>\d+)차시"
            ),
            priority=1,
            description="{교과목} {연도} {N}학기 {교수} {N}주차 {M}차시",
        ),
        TitlePattern(
            name="co_teaching",
            pattern=re.compile(
                r"^(?P<year_pair>\d{2}-[12](?:/\d{2}-[12])?)\s+"
                r"(?P<professor>[가-힣]{2,4}(?:/[가-힣]{2,4})+)\s+"
                r"(?P<course>\S+(?:\s+\S+)*?)\s+"
                r"(?P<week>\d+)주차\s+(?P<session>\d+)차시"
                r"(?:\s*\((?P<department>[^)]+)\))?"
            ),
            priority=2,
            description="co-teaching: {교수}/{교수} {교과목}",
        ),
        TitlePattern(
            name="academic_year",
            pattern=re.compile(
                r"^(?P<year>\d{4})학년도\s+(?P<semester>[12])학기\s+"
                r"(?P<course>\S+(?:\s+\S+)*?)\s+"
                r"(?P<week>\d+)주차"
                r"(?:[_\s]*(?P<session>\d+)차시)?"
                r"(?:[_\s]*(?P<extra>[^()\s]+))?"
                r"(?:\s*\((?P<professor>[^)]+)\))?"
            ),
            priority=3,
            description="{연도}학년도 {N}학기 {교과목} {N}주차 ({교수})",
        ),
        TitlePattern(
            name="numbered_prefix",
            pattern=re.compile(
                r"^[\d]+-[\d]+[.\s]+\s*(?P<professor>[가-힣]{2,4})\s+"
                r"(?P<course>\S+(?:\s+\S+)*?)\s+"
                r"(?P<week>\d+)주차\s+(?P<session>\d+)차시"
                r"(?:-\d+)?"
                r"(?:\s*\(?(?P<department>[^)]*(?:학과|과))\)?)?"
            ),
            priority=4,
            description="{번호}.{교수} {교과목} {N}주차 {M}차시({학과})",
        ),
        TitlePattern(
            name="standard_kr",
            pattern=re.compile(
                r"^(?P<professor>[가-힣]{2,4})\s+(?P<year>\d{4})\s+"
                r"(?:(?P<department>\S+(?:학과|과))\s+)?"
                r"(?P<course>\S+(?:\s+\S+)*?)\s+"
                r"(?P<week>\d+)주차\s+(?P<session>\d+)차시"
            ),
            priority=5,
            description="{교수} {연도} {학과} {교과목} {N}주차 {M}차시",
        ),
        # year_prof_course_week: {연도} {교수} {교과목} {N}주차
        TitlePattern(
            name="year_prof_course_week",
            pattern=re.compile(
                r"^(?P<year>\d{4})\s+(?P<professor>[가-힣]{2,4})\s+"
                r"(?P<course>\S+(?:\s+\S+)*?)\s+"
                r"(?P<week>\d+)주차"
                r"(?:\s+(?P<session>\d+)차시)?"
            ),
            priority=6,
            description="{연도} {교수} {교과목} {N}주차",
        ),
        # year_course_week_session_prof: {연도} {교과목} {N}주차 {M}차시 ... ({교수})
        TitlePattern(
            name="year_course_week_prof",
            pattern=re.compile(
                r"^(?P<year>\d{4})\s+"
                r"(?P<course>\S+(?:\s+\S+)*?)\s+"
                r"(?P<week>\d+)주차"
                r"(?:[_\s]*(?P<session>\d+)차시)?"
                r"(?:\s+\S+)*?"
                r"\s*\((?P<professor>[^)]+)\)"
            ),
            priority=7,
            description="{연도} {교과목} {N}주차 {M}차시 ({교수})",
        ),
        # prof_year_course_week_only: {교수} {연도} {교과목} {keyword}? {N}주차
        TitlePattern(
            name="prof_year_course_week_only",
            pattern=re.compile(
                r"^(?P<professor>[가-힣]{2,4})\s+(?P<year>\d{4})\s+"
                r"(?:(?P<department>\S+(?:학과|과))\s+)?"
                r"(?P<course>\S+(?:\s+\S+)*?)\s+"
                r"(?P<week>\d+)주차"
            ),
            priority=8,
            description="{교수} {연도} {교과목} {N}주차 (no session)",
        ),
        # year_semester_prefix: {연도}-{학기} {교수} {교과목} {N}주차
        TitlePattern(
            name="year_semester_prefix",
            pattern=re.compile(
                r"^(?P<year_pair>\d{4}-[12])\s+"
                r"(?P<professor>[가-힣]{2,4})\s+"
                r"(?:(?P<department>\S+(?:학과|과))\s+)?"
                r"(?P<course>\S+(?:\s+\S+)*?)\s+"
                r"(?P<week>\d+)주차\s+(?P<session>\d+)차시"
            ),
            priority=9,
            description="{연도}-{학기} {교수} {학과} {교과목} {N}주차 {M}차시",
        ),
        # prof_keyword_course: {교수} {특강|OT} {교과목}
        TitlePattern(
            name="prof_keyword_course",
            pattern=re.compile(
                r"^(?P<professor>[가-힣]{2,4})\s+"
                r"(?P<supp_keyword>특강|OT)\s+"
                r"(?P<course>\S+(?:\s+\S+)*?)$"
            ),
            priority=10,
            description="{교수} {특강|OT} {교과목}",
        ),
        # prof_year_course_supplementary: {교수} {연도} {학과}? {교과목} OT
        TitlePattern(
            name="prof_supplementary",
            pattern=re.compile(
                r"^(?P<professor>[가-힣]{2,4})\s+"
                r"(?:(?P<year>\d{4})\s+)?"
                r"(?:(?P<department>\S+(?:학과|과))\s+)?"
                r"(?P<course>\S+(?:\s+\S+)*?)\s+"
                r"(?P<supp_keyword>OT|특강|핵심영상|보완영상|질문응답|보충)"
            ),
            priority=11,
            description="{교수} {연도}? {교과목} {supplementary}",
        ),
        # dept_first: {학과} ... {교과목} {연도} {N}주차 {M}차시 ... {교수}
        TitlePattern(
            name="dept_first",
            pattern=re.compile(
                r"^(?P<department>\S+(?:학과|과))\s+\S+\s+"
                r"(?P<course>\S+(?:\s+\S+)*?)\s+"
                r"(?P<year>\d{4})\s+"
                r"(?P<week>\d+)주차\s+(?P<session>\d+)차시"
                r"(?:\s+\S+)*\s+(?P<professor>[가-힣]{2,4})$"
            ),
            priority=12,
            description="{학과} ... {교과목} {연도} {N}주차 {M}차시 ... {교수}",
        ),
    ]
    return sorted(patterns, key=lambda p: p.priority)


def _extract_professors(raw: str) -> list[str]:
    """Extract professor names from a raw string.

    Args:
        raw: Raw professor string, possibly slash-separated or parenthesized.

    Returns:
        List of professor names.
    """
    if not raw:
        return []
    # Remove surrounding parentheses
    raw = raw.strip("() ")
    # Split on slash
    names = [n.strip() for n in raw.split("/") if n.strip()]
    return names


def _classify_category(title: str) -> str:
    """Classify video as regular or supplementary based on keywords.

    Args:
        title: Original video title.

    Returns:
        "supplementary" if any keyword found, else "regular".
    """
    for keyword in SUPPLEMENTARY_KEYWORDS:
        if keyword in title:
            return "supplementary"
    return "regular"


def _fallback_parse(title: str, video_id: str) -> ParsedTitle:
    """Attempt to extract individual fields when no full pattern matches.

    Args:
        title: Original video title.
        video_id: YouTube video ID.

    Returns:
        ParsedTitle with whatever fields could be extracted, parse_error=True.
    """
    week = None
    session = None
    year = None
    semester = None
    professor: list[str] = []
    course = None
    department = None

    # Extract week
    week_match = re.search(r"(\d+)주차", title)
    if week_match:
        week = int(week_match.group(1))

    # Extract session
    session_match = re.search(r"(\d+)차시", title)
    if session_match:
        session = int(session_match.group(1))

    # Extract year (4-digit number, 2000-2099)
    year_match = re.search(r"(?<!\d)(20\d{2})(?!\d)", title)
    if year_match:
        year = int(year_match.group(1))

    # Extract semester
    sem_match = re.search(r"([12])학기", title)
    if sem_match:
        semester = int(sem_match.group(1))

    # Extract professor from parenthesized form
    prof_paren = re.search(r"\(([가-힣]{2,4}(?:/[가-힣]{2,4})*)\)", title)
    if prof_paren:
        professor = _extract_professors(prof_paren.group(1))

    # Extract professor from start of title (Korean name, 2-4 chars)
    if not professor:
        prof_start = re.match(r"^(?:\d+[-\s.]*)?([가-힣]{2,4})\s", title)
        if prof_start:
            professor = [prof_start.group(1)]

    # Extract department
    dept_match = re.search(r"([가-힣]+(?:학과|과))", title)
    if dept_match:
        department = dept_match.group(1)

    category = _classify_category(title)

    return ParsedTitle(
        video_id=video_id,
        original_title=title,
        professor=professor,
        course=course,
        year=year,
        semester=semester,
        week=week,
        session=session,
        department=department,
        category=category,
        parse_error=True,
        matched_pattern=None,
    )


class TitleParser:
    """Parser for Korean university lecture video titles.

    Uses priority-ordered regex patterns to extract structured fields
    from video titles. Falls back to individual field extraction when
    no full pattern matches.
    """

    def __init__(self) -> None:
        self._patterns = _build_patterns()

    def parse(self, title: str, video_id: str) -> ParsedTitle:
        """Parse a single video title into structured fields.

        Args:
            title: Video title string.
            video_id: YouTube video ID.

        Returns:
            ParsedTitle with extracted fields.
        """
        if not title or not title.strip():
            return ParsedTitle(
                video_id=video_id,
                original_title=title if title and title.strip() else "(empty)",
                parse_error=True,
                matched_pattern=None,
                category=_classify_category(title) if title else "regular",
            )

        category = _classify_category(title)

        for tp in self._patterns:
            m = tp.pattern.search(title)
            if m:
                groups = m.groupdict()
                professor_raw = groups.get("professor", "")
                professors = _extract_professors(professor_raw)

                year = None
                if "year" in groups and groups["year"]:
                    year = int(groups["year"])
                elif "year_pair" in groups and groups["year_pair"]:
                    yp = groups["year_pair"]
                    # Try 4-digit year first (e.g., "2025-1")
                    four_digit = re.match(r"(\d{4})", yp)
                    if four_digit:
                        year = int(four_digit.group(1))
                    else:
                        # 2-digit year (e.g., "24-1/25-1")
                        two_digit = re.match(r"(\d{2})", yp)
                        if two_digit:
                            year = 2000 + int(two_digit.group(1))

                semester = None
                if "semester" in groups and groups["semester"]:
                    semester = int(groups["semester"])
                elif "year_pair" in groups and groups["year_pair"]:
                    yp = groups["year_pair"]
                    sem_m = re.search(r"\d+-([12])", yp)
                    if sem_m:
                        semester = int(sem_m.group(1))

                week = int(groups["week"]) if groups.get("week") else None
                session = int(groups["session"]) if groups.get("session") else None
                course = groups.get("course")
                department = groups.get("department")

                return ParsedTitle(
                    video_id=video_id,
                    original_title=title,
                    professor=professors,
                    course=course,
                    year=year,
                    semester=semester,
                    week=week,
                    session=session,
                    department=department,
                    category=category,
                    parse_error=False,
                    matched_pattern=tp.name,
                )

        return _fallback_parse(title, video_id)

    def parse_batch(
        self, videos: list[dict]
    ) -> tuple[list[ParsedTitle], dict[str, int | float]]:
        """Parse a batch of videos and return results with stats.

        Args:
            videos: List of dicts with 'video_id' and 'title' keys.

        Returns:
            Tuple of (list of ParsedTitle, stats dict with total,
            success_count, error_count, success_rate).
        """
        if not videos:
            return [], {
                "total": 0,
                "success_count": 0,
                "error_count": 0,
                "success_rate": 0.0,
            }

        results: list[ParsedTitle] = []
        for video in videos:
            parsed = self.parse(video["title"], video["video_id"])
            results.append(parsed)

        total = len(results)
        error_count = sum(1 for r in results if r.parse_error)
        success_count = total - error_count

        return results, {
            "total": total,
            "success_count": success_count,
            "error_count": error_count,
            "success_rate": success_count / total if total > 0 else 0.0,
        }

    def save_results(
        self, results: list[ParsedTitle], output_dir: Path
    ) -> Path:
        """Save parsed results to a JSON file in the output directory.

        Args:
            results: List of ParsedTitle to save.
            output_dir: Directory to save parsed_titles.json into.

        Returns:
            Path to the saved file.
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / "parsed_titles.json"
        data = [r.model_dump() for r in results]
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return output_path
