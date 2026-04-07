"""Quality checker service for lecture video content.

Implements Q-001 through Q-005 quality rules to assess basic
educational content quality from caption data and video metadata.
"""

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

# Default thresholds
DEFAULT_MIN_DURATION_SECONDS = 300  # 5 minutes
DEFAULT_RELEVANCE_THRESHOLD = 0.10
DEFAULT_SILENCE_THRESHOLD = 0.30
DEFAULT_DENSITY_MIN = 200.0
DEFAULT_DENSITY_MAX = 600.0


@dataclass
class QualityResult:
    """Result of all quality checks for a single video.

    Attributes:
        q001_voice_present: Has extractable captions.
        q002_min_duration: Duration >= minimum threshold.
        q003_course_relevance: Proportion of course-related terms.
        q004_silence_ratio: Ratio of inter-segment gaps.
        q005_speech_density: Characters per minute.
        pass_count: Number of rules passed (0-5).
    """

    q001_voice_present: bool = False
    q002_min_duration: bool = False
    q003_course_relevance: float | None = None
    q004_silence_ratio: float | None = None
    q005_speech_density: float | None = None
    pass_count: int = 0


class QualityChecker:
    """Service for running quality checks on video content.

    Args:
        min_duration_seconds: Minimum video duration for Q-002.
        relevance_threshold: Minimum course relevance score for Q-003.
        silence_threshold: Maximum silence ratio for Q-004.
        density_min: Minimum speech density (chars/min) for Q-005.
        density_max: Maximum speech density (chars/min) for Q-005.
    """

    def __init__(
        self,
        min_duration_seconds: int = DEFAULT_MIN_DURATION_SECONDS,
        relevance_threshold: float = DEFAULT_RELEVANCE_THRESHOLD,
        silence_threshold: float = DEFAULT_SILENCE_THRESHOLD,
        density_min: float = DEFAULT_DENSITY_MIN,
        density_max: float = DEFAULT_DENSITY_MAX,
    ) -> None:
        """Initialize with configurable thresholds.

        Args:
            min_duration_seconds: Minimum video duration for Q-002.
            relevance_threshold: Minimum course relevance for Q-003.
            silence_threshold: Maximum silence ratio for Q-004.
            density_min: Min speech density (chars/min) for Q-005.
            density_max: Max speech density (chars/min) for Q-005.
        """
        self._min_duration = min_duration_seconds
        self._relevance_threshold = relevance_threshold
        self._silence_threshold = silence_threshold
        self._density_min = density_min
        self._density_max = density_max

    def check_voice_presence(
        self, segments: list[dict[str, Any]] | None
    ) -> bool:
        """Q-001: Check if video has extractable voice/captions.

        Args:
            segments: Caption segments, or None if no captions.

        Returns:
            True if captions exist and are non-empty.
        """
        return segments is not None and len(segments) > 0

    def check_min_duration(self, duration_seconds: int) -> bool:
        """Q-002: Check if video meets minimum duration.

        Args:
            duration_seconds: Video duration in seconds.

        Returns:
            True if duration >= threshold.
        """
        return duration_seconds >= self._min_duration

    def check_course_relevance(
        self,
        segments: list[dict[str, Any]],
        course_name: str | None,
    ) -> float | None:
        """Q-003: Check proportion of course-related terms in captions.

        Args:
            segments: Caption segments.
            course_name: Course name to check relevance against.

        Returns:
            Relevance score (0.0-1.0), or None if cannot compute.
        """
        if not segments or course_name is None:
            return None

        full_text = " ".join(seg.get("text", "") for seg in segments)
        if not full_text.strip():
            return None

        words = full_text.split()
        if not words:
            return None

        # Count occurrences of course name terms in the text
        course_terms = set(course_name.split())
        matching = sum(1 for w in words if w in course_terms)
        return matching / len(words)

    def check_silence_ratio(
        self,
        segments: list[dict[str, Any]],
        total_duration: float,
    ) -> float | None:
        """Q-004: Check ratio of inter-segment gaps (silence).

        Args:
            segments: Caption segments with start and duration.
            total_duration: Total video duration in seconds.

        Returns:
            Silence ratio (0.0-1.0), or None if cannot compute.
        """
        if not segments or total_duration <= 0:
            return None

        spoken_time = sum(seg.get("duration", 0.0) for seg in segments)
        silence_time = max(0.0, total_duration - spoken_time)
        return silence_time / total_duration

    def check_speech_density(
        self,
        segments: list[dict[str, Any]],
        total_duration: float,
    ) -> float | None:
        """Q-005: Check speech density (characters per minute).

        Args:
            segments: Caption segments.
            total_duration: Total video duration in seconds.

        Returns:
            Characters per minute, or None if cannot compute.
        """
        if not segments or total_duration <= 0:
            return None

        total_chars = sum(len(seg.get("text", "")) for seg in segments)
        total_minutes = total_duration / 60.0
        return total_chars / total_minutes

    def run_all_checks(
        self,
        *,
        segments: list[dict[str, Any]] | None,
        duration_seconds: int,
        course_name: str | None = None,
    ) -> QualityResult:
        """Run all Q-001~Q-005 quality checks.

        Args:
            segments: Caption segments, or None if no captions.
            duration_seconds: Video duration in seconds.
            course_name: Course name for relevance check.

        Returns:
            QualityResult with all check results and pass count.
        """
        q001 = self.check_voice_presence(segments)
        q002 = self.check_min_duration(duration_seconds)

        q003: float | None = None
        q004: float | None = None
        q005: float | None = None

        if segments:
            q003 = self.check_course_relevance(segments, course_name)
            q004 = self.check_silence_ratio(segments, float(duration_seconds))
            q005 = self.check_speech_density(segments, float(duration_seconds))

        # Count passes
        pass_count = 0
        if q001:
            pass_count += 1
        if q002:
            pass_count += 1
        if q003 is not None and q003 >= self._relevance_threshold:
            pass_count += 1
        if q004 is not None and q004 < self._silence_threshold:
            pass_count += 1
        if q005 is not None and self._density_min <= q005 <= self._density_max:
            pass_count += 1

        return QualityResult(
            q001_voice_present=q001,
            q002_min_duration=q002,
            q003_course_relevance=q003,
            q004_silence_ratio=q004,
            q005_speech_density=q005,
            pass_count=pass_count,
        )
