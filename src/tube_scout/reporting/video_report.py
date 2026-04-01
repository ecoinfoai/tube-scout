"""Video report generator."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader

from tube_scout.storage.json_store import read_json


class VideoReportGenerator:
    """Generate HTML reports for individual videos."""

    def __init__(self, data_dir: Path) -> None:
        """Initialize with data directory.

        Args:
            data_dir: Root data directory.
        """
        self.data_dir = data_dir
        templates_dir = Path(__file__).parent / "templates"
        self._env = Environment(
            loader=FileSystemLoader(str(templates_dir)),
            autoescape=True,
        )

    def generate(
        self,
        video_id: str,
        channel_id: str,
        output_dir: Path,
    ) -> Path:
        """Generate an HTML report for a video.

        Args:
            video_id: YouTube video ID.
            channel_id: YouTube channel ID.
            output_dir: Output directory for the report.

        Returns:
            Path to the generated HTML file.
        """
        video = self._load_video_meta(video_id, channel_id)
        retention = self._load_retention(video_id)
        segments = self._load_segments(video_id)
        suggestions = generate_suggestions(video, retention, segments)

        template = self._env.get_template("video_report.html")
        html = template.render(
            video=video,
            retention=retention,
            segments=segments,
            suggestions=suggestions,
            generated_at=datetime.now(UTC).isoformat(),
        )

        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"{video_id}.html"
        output_path.write_text(html, encoding="utf-8")
        return output_path

    def _load_video_meta(self, video_id: str, channel_id: str) -> dict[str, Any]:
        """Load video metadata."""
        videos_path = (
            self.data_dir / "raw" / "channels" / channel_id / "videos_meta.json"
        )
        videos = read_json(videos_path)
        if videos:
            vlist = videos if isinstance(videos, list) else videos.get("videos", [])
            for v in vlist:
                if v.get("video_id") == video_id:
                    return v
        return {"video_id": video_id, "title": video_id}

    def _load_retention(self, video_id: str) -> dict[str, Any] | None:
        """Load retention analysis results."""
        path = self.data_dir / "processed" / "retention" / f"{video_id}.json"
        return read_json(path)

    def _load_segments(self, video_id: str) -> list[dict[str, Any]] | None:
        """Load transcript segments."""
        path = self.data_dir / "processed" / "segments" / f"{video_id}.json"
        return read_json(path)


def generate_suggestions(
    video: dict[str, Any],
    retention: dict[str, Any] | None,
    segments: list[dict[str, Any]] | None,
) -> list[str]:
    """Generate improvement suggestions based on analysis data.

    Args:
        video: Video metadata.
        retention: Retention analysis results.
        segments: Transcript segments.

    Returns:
        List of suggestion strings.
    """
    suggestions: list[str] = []

    duration = video.get("duration_seconds", 0)
    if duration > 1800:
        suggestions.append(
            f"Video is {duration // 60} minutes long. "
            "Consider splitting into shorter segments (15-20 min) for better retention."
        )

    if retention:
        hotspots = retention.get("hotspots", [])
        skip_zones = retention.get("skip_zones", [])
        if hotspots:
            suggestions.append(
                f"Found {len(hotspots)} rewatch hotspot(s). "
                "These sections may be confusing — "
                "consider adding visual aids or examples."
            )
        if skip_zones:
            suggestions.append(
                f"Found {len(skip_zones)} skip zone(s). "
                "Consider making these sections more engaging or condensing them."
            )

    if segments:
        high_difficulty = [s for s in segments if s.get("difficulty_score", 0) > 0.7]
        if high_difficulty:
            suggestions.append(
                f"Found {len(high_difficulty)} high-difficulty segment(s). "
                "Consider adding prerequisite explanations "
                "or breaking down complex concepts."
            )

    return suggestions
