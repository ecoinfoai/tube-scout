"""SRT subtitle format parser.

Converts SRT text into a list of segment dicts compatible with
the existing transcript format: {"text": str, "start": float, "duration": float}.
"""

import re
from typing import Any

TIMESTAMP_RE = re.compile(
    r"(\d{2}):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2})[,.](\d{3})"
)


def _parse_timestamp(hours: str, minutes: str, seconds: str, millis: str) -> float:
    """Convert timestamp components to seconds.

    Args:
        hours: Hours component.
        minutes: Minutes component.
        seconds: Seconds component.
        millis: Milliseconds component.

    Returns:
        Time in seconds as float.
    """
    return int(hours) * 3600 + int(minutes) * 60 + int(seconds) + int(millis) / 1000


def parse_srt(srt_text: str) -> list[dict[str, Any]]:
    """Parse SRT-format subtitle text into segment dicts.

    Args:
        srt_text: Raw SRT content string.

    Returns:
        List of segment dicts with 'text', 'start', and 'duration' keys.
        Malformed entries are skipped with a warning logged.
    """
    if not srt_text or not srt_text.strip():
        return []

    # Strip BOM if present
    srt_text = srt_text.lstrip("\ufeff")

    segments: list[dict[str, Any]] = []
    blocks = re.split(r"\n\n+", srt_text.strip())

    for block in blocks:
        lines = block.strip().split("\n")
        if len(lines) < 2:
            continue

        # Find timestamp line
        timestamp_match = None
        timestamp_line_idx = -1
        for i, line in enumerate(lines):
            match = TIMESTAMP_RE.search(line)
            if match:
                timestamp_match = match
                timestamp_line_idx = i
                break

        if timestamp_match is None:
            continue

        start = _parse_timestamp(
            timestamp_match.group(1),
            timestamp_match.group(2),
            timestamp_match.group(3),
            timestamp_match.group(4),
        )
        end = _parse_timestamp(
            timestamp_match.group(5),
            timestamp_match.group(6),
            timestamp_match.group(7),
            timestamp_match.group(8),
        )
        duration = end - start

        # Text is everything after the timestamp line
        text_lines = lines[timestamp_line_idx + 1 :]
        text = "\n".join(text_lines).strip()
        if not text:
            continue

        segments.append({
            "text": text,
            "start": start,
            "duration": duration,
        })

    return segments
