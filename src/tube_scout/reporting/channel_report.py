"""Channel report generator."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader

from tube_scout.storage.json_store import read_json


class ChannelReportGenerator:
    """Generate HTML reports for channels."""

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
        channel_id: str,
        output_dir: Path,
    ) -> Path:
        """Generate an HTML report for a channel.

        Args:
            channel_id: YouTube channel ID.
            output_dir: Output directory.

        Returns:
            Path to the generated HTML file.
        """
        channel = self._load_channel_meta(channel_id)
        videos = self._load_videos(channel_id)
        total_views = sum(v.get("view_count", 0) for v in videos)
        insights = self._generate_insights(videos)

        template = self._env.get_template("channel_report.html")
        html = template.render(
            channel=channel,
            videos=videos,
            total_views=total_views,
            insights=insights,
            generated_at=datetime.now(UTC).isoformat(),
        )

        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"{channel_id}.html"
        output_path.write_text(html, encoding="utf-8")
        return output_path

    def _load_channel_meta(self, channel_id: str) -> dict[str, Any]:
        """Load channel metadata."""
        path = self.data_dir / "raw" / "channels" / channel_id / "channel_meta.json"
        data = read_json(path)
        return data or {"channel_id": channel_id, "channel_name": channel_id}

    def _load_videos(self, channel_id: str) -> list[dict[str, Any]]:
        """Load all video metadata for a channel."""
        path = self.data_dir / "raw" / "channels" / channel_id / "videos_meta.json"
        data = read_json(path)
        if data is None:
            return []
        return data if isinstance(data, list) else data.get("videos", [])

    def _generate_insights(self, videos: list[dict[str, Any]]) -> list[str]:
        """Generate channel-level insights."""
        if not videos:
            return ["No videos to analyze."]

        insights = []
        views = [v.get("view_count", 0) for v in videos]
        avg_views = sum(views) / len(views)
        insights.append(f"Average views per video: {avg_views:.0f}")

        durations = [
            v.get("duration_seconds", 0) for v in videos if v.get("duration_seconds")
        ]
        if durations:
            avg_duration = sum(durations) / len(durations) / 60
            insights.append(f"Average video length: {avg_duration:.1f} minutes")

        return insights
