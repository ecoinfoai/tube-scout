"""Comment insight report generator."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader


class CommentReportGenerator:
    """Generate HTML comment insight reports with topic summaries and FAQ.

    Produces reports satisfying FR-022: per-topic sentiment summaries
    and auto-extracted FAQ section.
    """

    def __init__(self) -> None:
        """Initialize the report generator with Jinja2 template environment."""
        templates_dir = Path(__file__).parent / "templates"
        self._env = Environment(
            loader=FileSystemLoader(str(templates_dir)),
            autoescape=True,
        )

    def generate(
        self,
        video_id: str,
        video_meta: dict[str, Any],
        topics: list[dict[str, Any]],
        questions_data: dict[str, Any],
        output_dir: Path,
    ) -> Path:
        """Generate an HTML comment insight report.

        Args:
            video_id: YouTube video ID.
            video_meta: Video metadata dict (title, view_count, etc.).
            topics: List of TopicCluster dicts from topic extraction.
            questions_data: Dict with 'questions' and 'hotspot_matches' lists.
            output_dir: Output directory for the report file.

        Returns:
            Path to the generated HTML file.
        """
        questions = questions_data.get("questions", [])
        hotspot_matches = questions_data.get("hotspot_matches", [])

        template = self._env.get_template("comment_insight.html")
        html = template.render(
            video=video_meta,
            video_id=video_id,
            topics=topics,
            questions=questions,
            hotspot_matches=hotspot_matches,
            total_comments=sum(
                len(t.get("comment_ids", [])) for t in topics
            ),
            generated_at=datetime.now(UTC).isoformat(),
        )

        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"{video_id}_comment_insight.html"
        output_path.write_text(html, encoding="utf-8")
        return output_path
