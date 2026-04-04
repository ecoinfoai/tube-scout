"""Title validation rules engine for lecture video titles."""

import json
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any

from tube_scout.models.parsed_title import ParsedTitle
from tube_scout.models.validation import ValidationFinding

SEVERITY_ORDER = {"ERROR": 0, "WARNING": 1, "INFO": 2}


def _levenshtein_distance(s1: str, s2: str) -> int:
    """Compute Levenshtein edit distance between two strings.

    Args:
        s1: First string.
        s2: Second string.

    Returns:
        Integer edit distance.
    """
    if len(s1) < len(s2):
        return _levenshtein_distance(s2, s1)
    if len(s2) == 0:
        return len(s1)

    prev_row = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1):
        curr_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = prev_row[j + 1] + 1
            deletions = curr_row[j] + 1
            substitutions = prev_row[j] + (c1 != c2)
            curr_row.append(min(insertions, deletions, substitutions))
        prev_row = curr_row

    return prev_row[-1]


def _get_upload_year(video: dict) -> int | None:
    """Extract upload year from video metadata.

    Args:
        video: Video metadata dict with published_at key.

    Returns:
        Upload year as integer, or None if not parseable.
    """
    published_at = video.get("published_at", "")
    if not published_at or len(published_at) < 4:
        return None
    try:
        return int(published_at[:4])
    except ValueError:
        return None


def _build_video_map(videos: list[dict]) -> dict[str, dict]:
    """Build a video_id -> video metadata lookup.

    Args:
        videos: List of video metadata dicts.

    Returns:
        Dict mapping video_id to video metadata.
    """
    return {v["video_id"]: v for v in videos if "video_id" in v}


def check_year_mismatch(
    parsed_titles: list[ParsedTitle],
    videos: list[dict],
) -> list[ValidationFinding]:
    """V-001: Detect year mismatch between title year and upload year.

    Args:
        parsed_titles: List of parsed titles.
        videos: List of video metadata dicts.

    Returns:
        List of ValidationFinding for year mismatches (difference > 1).
    """
    video_map = _build_video_map(videos)
    findings: list[ValidationFinding] = []

    for pt in parsed_titles:
        if pt.year is None:
            continue
        video = video_map.get(pt.video_id)
        if video is None:
            continue
        upload_year = _get_upload_year(video)
        if upload_year is None:
            continue
        if abs(pt.year - upload_year) > 1:
            findings.append(
                ValidationFinding(
                    rule_id="V-001",
                    severity="WARNING",
                    video_ids=[pt.video_id],
                    description=(
                        f"Title year {pt.year} differs from upload year "
                        f"{upload_year} by more than 1 year"
                    ),
                    details={
                        "title_year": pt.year,
                        "upload_year": upload_year,
                        "difference": abs(pt.year - upload_year),
                    },
                )
            )

    return findings


def check_duplicates(
    parsed_titles: list[ParsedTitle],
) -> list[ValidationFinding]:
    """V-002: Detect duplicate videos with same professor+course+week+session.

    Args:
        parsed_titles: List of parsed titles.

    Returns:
        List of ValidationFinding for duplicate combinations.
    """
    groups: dict[tuple, list[str]] = defaultdict(list)

    for pt in parsed_titles:
        if pt.week is None or pt.session is None or not pt.professor or not pt.course:
            continue
        for prof in pt.professor:
            key = (prof, pt.course, pt.week, pt.session)
            groups[key].append(pt.video_id)

    findings: list[ValidationFinding] = []
    for key, video_ids in groups.items():
        if len(video_ids) >= 2:
            prof, course, week, session = key
            findings.append(
                ValidationFinding(
                    rule_id="V-002",
                    severity="ERROR",
                    video_ids=video_ids,
                    professor=prof,
                    description=(
                        f"Duplicate: {prof} {course} week {week} session {session} "
                        f"appears {len(video_ids)} times"
                    ),
                    details={
                        "professor": prof,
                        "course": course,
                        "week": week,
                        "session": session,
                        "count": len(video_ids),
                    },
                )
            )

    return findings


def check_invalid_week(
    parsed_titles: list[ParsedTitle],
) -> list[ValidationFinding]:
    """V-003: Detect invalid week numbers (> 16 or <= 0).

    Args:
        parsed_titles: List of parsed titles.

    Returns:
        List of ValidationFinding for invalid weeks.
    """
    findings: list[ValidationFinding] = []

    for pt in parsed_titles:
        if pt.week is None:
            continue
        if pt.week <= 0 or pt.week > 16:
            findings.append(
                ValidationFinding(
                    rule_id="V-003",
                    severity="ERROR",
                    video_ids=[pt.video_id],
                    description=f"Invalid week number: {pt.week}",
                    details={"week": pt.week},
                )
            )

    return findings


def check_name_inconsistency(
    parsed_titles: list[ParsedTitle],
) -> list[ValidationFinding]:
    """V-004: Detect professor name inconsistencies via edit distance.

    Args:
        parsed_titles: List of parsed titles.

    Returns:
        List of ValidationFinding for similar but not identical names.
    """
    # Collect all unique professor names with their video_ids
    name_videos: dict[str, list[str]] = defaultdict(list)
    for pt in parsed_titles:
        for prof in pt.professor:
            name_videos[prof].append(pt.video_id)

    names = list(name_videos.keys())
    findings: list[ValidationFinding] = []
    seen_pairs: set[tuple[str, str]] = set()

    for i, name1 in enumerate(names):
        for j in range(i + 1, len(names)):
            name2 = names[j]
            dist = _levenshtein_distance(name1, name2)
            if 0 < dist <= 2:
                pair = tuple(sorted([name1, name2]))
                if pair in seen_pairs:
                    continue
                seen_pairs.add(pair)
                all_video_ids = list(
                    set(name_videos[name1] + name_videos[name2])
                )
                findings.append(
                    ValidationFinding(
                        rule_id="V-004",
                        severity="WARNING",
                        video_ids=all_video_ids,
                        description=(
                            f"Professor name inconsistency: '{name1}' vs "
                            f"'{name2}' (edit distance {dist})"
                        ),
                        details={
                            "name1": name1,
                            "name2": name2,
                            "edit_distance": dist,
                        },
                    )
                )

    return findings


def check_parse_failures(
    parsed_titles: list[ParsedTitle],
) -> list[ValidationFinding]:
    """V-005: Flag titles that failed to parse.

    Args:
        parsed_titles: List of parsed titles.

    Returns:
        List of ValidationFinding for parse failures.
    """
    findings: list[ValidationFinding] = []

    for pt in parsed_titles:
        if pt.parse_error:
            findings.append(
                ValidationFinding(
                    rule_id="V-005",
                    severity="WARNING",
                    video_ids=[pt.video_id],
                    description=(
                        f"Title could not be fully parsed: "
                        f"'{pt.original_title[:80]}'"
                    ),
                    details={"original_title": pt.original_title},
                )
            )

    return findings


def check_session_gaps(
    parsed_titles: list[ParsedTitle],
) -> list[ValidationFinding]:
    """V-006: Detect session gaps (session N without session N-1).

    Args:
        parsed_titles: List of parsed titles.

    Returns:
        List of ValidationFinding for session continuity gaps.
    """
    # Group sessions by (professor, course, week) — only regular videos
    groups: dict[tuple, dict[int, str]] = defaultdict(dict)

    for pt in parsed_titles:
        if pt.category == "supplementary":
            continue
        if pt.session is None or pt.week is None or not pt.professor or not pt.course:
            continue
        for prof in pt.professor:
            key = (prof, pt.course, pt.week)
            groups[key][pt.session] = pt.video_id

    findings: list[ValidationFinding] = []
    for key, sessions in groups.items():
        prof, course, week = key
        if not sessions:
            continue
        max_session = max(sessions.keys())
        for s in range(2, max_session + 1):
            if s in sessions and (s - 1) not in sessions:
                findings.append(
                    ValidationFinding(
                        rule_id="V-006",
                        severity="WARNING",
                        video_ids=[sessions[s]],
                        professor=prof,
                        description=(
                            f"Session gap: {prof} {course} week {week} has "
                            f"session {s} but missing session {s - 1}"
                        ),
                        details={
                            "professor": prof,
                            "course": course,
                            "week": week,
                            "present_session": s,
                            "missing_session": s - 1,
                        },
                    )
                )

    return findings


def check_duration_outliers(
    parsed_titles: list[ParsedTitle],
    videos: list[dict],
) -> list[ValidationFinding]:
    """V-007: Detect duration outliers (> +/-3 sigma from course average).

    Args:
        parsed_titles: List of parsed titles.
        videos: List of video metadata dicts with duration_seconds.

    Returns:
        List of ValidationFinding for duration outliers.
    """
    video_map = _build_video_map(videos)

    # Group durations by course
    course_durations: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for pt in parsed_titles:
        if not pt.course:
            continue
        video = video_map.get(pt.video_id)
        if video is None:
            continue
        duration = video.get("duration_seconds", 0)
        if duration > 0:
            course_durations[pt.course].append((pt.video_id, float(duration)))

    findings: list[ValidationFinding] = []
    for course, items in course_durations.items():
        if len(items) < 3:
            continue
        durations = [d for _, d in items]
        mean = statistics.mean(durations)
        stdev = statistics.stdev(durations)
        if stdev == 0:
            continue

        for video_id, duration in items:
            z_score = abs(duration - mean) / stdev
            if z_score > 3:
                findings.append(
                    ValidationFinding(
                        rule_id="V-007",
                        severity="INFO",
                        video_ids=[video_id],
                        description=(
                            f"Duration outlier for course '{course}': "
                            f"{duration:.0f}s (mean: {mean:.0f}s, "
                            f"stdev: {stdev:.0f}s, z-score: {z_score:.1f})"
                        ),
                        details={
                            "course": course,
                            "duration": duration,
                            "mean": mean,
                            "stdev": stdev,
                            "z_score": z_score,
                        },
                    )
                )

    return findings


def check_missing_weeks(
    parsed_titles: list[ParsedTitle],
) -> list[ValidationFinding]:
    """V-008: Detect gaps in week sequences per professor+course.

    Args:
        parsed_titles: List of parsed titles.

    Returns:
        List of ValidationFinding for missing weeks.
    """
    # Group weeks by (professor, course) — only regular videos
    groups: dict[tuple, set[int]] = defaultdict(set)

    for pt in parsed_titles:
        if pt.category == "supplementary":
            continue
        if pt.week is None or not pt.professor or not pt.course:
            continue
        for prof in pt.professor:
            groups[(prof, pt.course)].add(pt.week)

    findings: list[ValidationFinding] = []
    for (prof, course), weeks in groups.items():
        if len(weeks) < 2:
            continue
        min_week = min(weeks)
        max_week = max(weeks)
        expected = set(range(min_week, max_week + 1))
        missing = sorted(expected - weeks)
        if missing:
            # Get any video_id for this professor+course
            relevant_ids = [
                pt.video_id
                for pt in parsed_titles
                if prof in pt.professor and pt.course == course and pt.week is not None
            ]
            findings.append(
                ValidationFinding(
                    rule_id="V-008",
                    severity="WARNING",
                    video_ids=relevant_ids[:1] if relevant_ids else ["unknown"],
                    professor=prof,
                    description=(
                        f"Missing weeks for {prof} {course}: "
                        f"weeks {missing} in range {min_week}-{max_week}"
                    ),
                    details={
                        "professor": prof,
                        "course": course,
                        "missing_weeks": missing,
                        "existing_weeks": sorted(weeks),
                    },
                )
            )

    return findings


def check_upload_gaps(
    parsed_titles: list[ParsedTitle],
    videos: list[dict],
) -> list[ValidationFinding]:
    """V-009: Detect 2+ consecutive weeks without uploads.

    Args:
        parsed_titles: List of parsed titles.
        videos: List of video metadata dicts.

    Returns:
        List of ValidationFinding for extended upload gaps.
    """
    # Group weeks by (professor, course) — regular videos only
    groups: dict[tuple, set[int]] = defaultdict(set)
    group_video_ids: dict[tuple, list[str]] = defaultdict(list)

    for pt in parsed_titles:
        if pt.category == "supplementary":
            continue
        if pt.week is None or not pt.professor or not pt.course:
            continue
        for prof in pt.professor:
            key = (prof, pt.course)
            groups[key].add(pt.week)
            group_video_ids[key].append(pt.video_id)

    findings: list[ValidationFinding] = []
    for key, weeks in groups.items():
        if len(weeks) < 2:
            continue
        prof, course = key
        sorted_weeks = sorted(weeks)

        for i in range(len(sorted_weeks) - 1):
            gap = sorted_weeks[i + 1] - sorted_weeks[i]
            if gap > 2:
                findings.append(
                    ValidationFinding(
                        rule_id="V-009",
                        severity="INFO",
                        video_ids=group_video_ids[key][:1],
                        professor=prof,
                        description=(
                            f"Upload gap: {prof} {course} has {gap - 1} "
                            f"consecutive weeks without upload between "
                            f"week {sorted_weeks[i]} and {sorted_weeks[i + 1]}"
                        ),
                        details={
                            "professor": prof,
                            "course": course,
                            "gap_start": sorted_weeks[i],
                            "gap_end": sorted_weeks[i + 1],
                            "gap_weeks": gap - 1,
                        },
                    )
                )

    return findings


def run_all_validations(
    parsed_titles: list[ParsedTitle],
    videos: list[dict],
    calendar: Any = None,
) -> list[ValidationFinding]:
    """Run all 9 validation rules and return sorted findings.

    Args:
        parsed_titles: List of parsed titles.
        videos: List of video metadata dicts.
        calendar: Optional academic calendar (reserved for future use).

    Returns:
        List of ValidationFinding sorted by severity (ERROR > WARNING > INFO).
    """
    if not parsed_titles:
        return []

    findings: list[ValidationFinding] = []
    findings.extend(check_year_mismatch(parsed_titles, videos))
    findings.extend(check_duplicates(parsed_titles))
    findings.extend(check_invalid_week(parsed_titles))
    findings.extend(check_name_inconsistency(parsed_titles))
    findings.extend(check_parse_failures(parsed_titles))
    findings.extend(check_session_gaps(parsed_titles))
    findings.extend(check_duration_outliers(parsed_titles, videos))
    findings.extend(check_missing_weeks(parsed_titles))
    findings.extend(check_upload_gaps(parsed_titles, videos))

    findings.sort(key=lambda f: SEVERITY_ORDER.get(f.severity, 99))
    return findings


def save_validation_results(
    findings: list[ValidationFinding],
    output_dir: Path,
) -> Path:
    """Save validation results to JSON in the output directory.

    Args:
        findings: List of validation findings.
        output_dir: Directory to save results into.

    Returns:
        Path to the saved JSON file.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "validation_results.json"
    data = [f.model_dump() for f in findings]
    with open(output_path, "w", encoding="utf-8") as fp:
        json.dump(data, fp, ensure_ascii=False, indent=2)
    return output_path
