"""Channel comprehensive report generator (FR-023, FR-024)."""

from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader
from pydantic import BaseModel, Field, field_validator

from tube_scout.storage.json_store import read_json, write_json

_VALID_CATEGORIES = {"length", "structure", "difficulty", "engagement", "content"}
_VALID_PRIORITIES = {"high", "medium", "low"}


class ImprovementSuggestion(BaseModel):
    """Data-driven recommendation for report output."""

    video_id: str | None = None
    category: str
    suggestion: str = Field(min_length=1)
    evidence: str = Field(min_length=1)
    priority: str

    @field_validator("category")
    @classmethod
    def validate_category(cls, v: str) -> str:
        """Validate category is one of the allowed values."""
        if v not in _VALID_CATEGORIES:
            raise ValueError(
                f"Invalid category: '{v}'. Must be one of {sorted(_VALID_CATEGORIES)}"
            )
        return v

    @field_validator("priority")
    @classmethod
    def validate_priority(cls, v: str) -> str:
        """Validate priority is one of the allowed values."""
        if v not in _VALID_PRIORITIES:
            raise ValueError(
                f"Invalid priority: '{v}'. Must be one of {sorted(_VALID_PRIORITIES)}"
            )
        return v


def compare_videos(videos: list[dict[str, Any]]) -> dict[str, Any]:
    """Compare videos by views, engagement, duration, and topics.

    Args:
        videos: List of video metadata dicts.

    Returns:
        Comparison dict with rankings, duration_analysis, topic_groups, summary.
    """
    if not videos:
        return {
            "rankings": {"by_views": [], "by_engagement_rate": []},
            "duration_analysis": {
                "avg_duration_minutes": 0,
                "optimal_range": {"min": 0, "max": 0},
            },
            "topic_groups": {},
            "summary": {
                "total_videos": 0,
                "total_views": 0,
                "avg_views": 0,
            },
        }

    # Rankings by views
    by_views = sorted(videos, key=lambda v: v.get("view_count", 0), reverse=True)

    # Rankings by engagement rate (likes + comments) / views
    def engagement_rate(v: dict[str, Any]) -> float:
        views = v.get("view_count", 0)
        if views == 0:
            return 0.0
        return (v.get("like_count", 0) + v.get("comment_count", 0)) / views

    by_engagement = sorted(videos, key=engagement_rate, reverse=True)

    # Duration analysis
    durations = [
        v.get("duration_seconds", 0) for v in videos if v.get("duration_seconds", 0) > 0
    ]
    avg_duration_min = (sum(durations) / len(durations) / 60) if durations else 0

    # Optimal range: duration of top 50% videos by views
    top_half = by_views[: max(1, len(by_views) // 2)]
    top_durations = [
        v.get("duration_seconds", 0) / 60
        for v in top_half
        if v.get("duration_seconds", 0) > 0
    ]
    optimal_min = min(top_durations) if top_durations else 0
    optimal_max = max(top_durations) if top_durations else 0

    # Topic groups based on tags
    topic_groups: dict[str, list[str]] = defaultdict(list)
    for v in videos:
        for tag in v.get("tags", []):
            topic_groups[tag].append(v.get("video_id", ""))

    # Summary
    total_views = sum(v.get("view_count", 0) for v in videos)

    return {
        "rankings": {
            "by_views": [
                {"video_id": v.get("video_id"), "title": v.get("title", ""),
                 "view_count": v.get("view_count", 0)}
                for v in by_views
            ],
            "by_engagement_rate": [
                {"video_id": v.get("video_id"), "title": v.get("title", ""),
                 "engagement_rate": round(engagement_rate(v), 4)}
                for v in by_engagement
            ],
        },
        "duration_analysis": {
            "avg_duration_minutes": round(avg_duration_min, 1),
            "optimal_range": {
                "min": round(optimal_min, 1),
                "max": round(optimal_max, 1),
            },
        },
        "topic_groups": dict(topic_groups),
        "summary": {
            "total_videos": len(videos),
            "total_views": total_views,
            "avg_views": round(total_views / len(videos)),
        },
    }


def generate_improvement_suggestions(
    videos: list[dict[str, Any]],
    eqs_scores: list[dict[str, Any]] | None = None,
    forecasts: list[dict[str, Any]] | None = None,
) -> list[ImprovementSuggestion]:
    """Generate data-driven improvement suggestions.

    Args:
        videos: List of video metadata dicts.
        eqs_scores: Optional list of EQS quality score dicts.
        forecasts: Optional list of forecast result dicts.

    Returns:
        List of ImprovementSuggestion instances.
    """
    if not videos:
        return []

    suggestions: list[ImprovementSuggestion] = []

    # --- Length suggestions ---
    durations = [v.get("duration_seconds", 0) for v in videos]
    avg_duration = sum(durations) / len(durations) if durations else 0

    for v in videos:
        dur = v.get("duration_seconds", 0)
        if dur > 3600:  # > 60 min
            suggestions.append(ImprovementSuggestion(
                video_id=v.get("video_id"),
                category="length",
                suggestion=(
                    f"Video is {dur // 60} minutes long. "
                    "Consider splitting into 15-20 minute segments "
                    "for better retention."
                ),
                evidence=(
                    f"Average duration is {avg_duration / 60:.0f} min. "
                    f"Videos over 60 min typically see significant drop-off."
                ),
                priority="high",
            ))
        elif dur > 2400:  # > 40 min
            suggestions.append(ImprovementSuggestion(
                video_id=v.get("video_id"),
                category="length",
                suggestion=(
                    f"Video is {dur // 60} minutes long. "
                    "Consider adding chapter markers or breaks."
                ),
                evidence=f"Average channel duration is {avg_duration / 60:.0f} min.",
                priority="medium",
            ))

    # --- Engagement suggestions ---
    for v in videos:
        view_count = v.get("view_count", 0)
        likes = v.get("like_count", 0)
        comments = v.get("comment_count", 0)

        if view_count > 0:
            eng_rate = (likes + comments) / view_count
            if eng_rate < 0.01 and view_count > 100:
                suggestions.append(ImprovementSuggestion(
                    video_id=v.get("video_id"),
                    category="engagement",
                    suggestion=(
                        "Low engagement rate. Add call-to-action prompts, "
                        "questions, or interactive elements."
                    ),
                    evidence=(
                        f"Engagement rate: {eng_rate:.3f} "
                        f"({likes} likes + {comments} comments / {view_count} views)."
                    ),
                    priority="high" if eng_rate < 0.005 else "medium",
                ))

    # --- Channel-level length suggestion ---
    if avg_duration > 0:
        comparison = compare_videos(videos)
        optimal = comparison["duration_analysis"]["optimal_range"]
        if optimal["min"] > 0 and optimal["max"] > 0:
            suggestions.append(ImprovementSuggestion(
                video_id=None,
                category="length",
                suggestion=(
                    f"Top-performing videos are "
                    f"{optimal['min']:.0f}-{optimal['max']:.0f} "
                    "minutes long. Target this range for new content."
                ),
                evidence=(
                    f"Based on {len(videos)} videos, average duration "
                    f"is {avg_duration / 60:.0f} min."
                ),
                priority="medium",
            ))

    # --- EQS-based content suggestions ---
    if eqs_scores:
        score_map = {s["video_id"]: s for s in eqs_scores}
        for v in videos:
            vid = v.get("video_id")
            if vid in score_map:
                score = score_map[vid]
                weak_axes = []
                for axis in ["relevance", "accuracy", "clarity", "engagement", "depth"]:
                    if score.get(axis, 0) < 0.6:
                        weak_axes.append(axis)
                if weak_axes:
                    suggestions.append(ImprovementSuggestion(
                        video_id=vid,
                        category="content",
                        suggestion=(
                            f"Low quality scores on: {', '.join(weak_axes)}. "
                            "Review and improve these aspects."
                        ),
                        evidence=(
                            f"EQS overall: {score.get('overall', 0):.2f}"
                            ", weak axes: "
                            + ", ".join(
                                f"{a}={score.get(a, 0):.2f}"
                                for a in weak_axes
                            )
                            + "."
                        ),
                        priority="high" if len(weak_axes) >= 2 else "medium",
                    ))

    # --- Channel-level engagement summary ---
    total_engagement = sum(
        v.get("like_count", 0) + v.get("comment_count", 0) for v in videos
    )
    total_views = sum(v.get("view_count", 0) for v in videos)
    if total_views > 0:
        channel_eng = total_engagement / total_views
        if channel_eng < 0.02:
            suggestions.append(ImprovementSuggestion(
                video_id=None,
                category="engagement",
                suggestion=(
                    "Channel engagement rate is below average. "
                    "Consider adding more interactive content and community engagement."
                ),
                evidence=f"Channel engagement rate: {channel_eng:.3f}.",
                priority="medium",
            ))

    return suggestions


class ChannelReportGenerator:
    """Generate comprehensive HTML reports for channels (FR-023)."""

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
        """Generate a comprehensive HTML report for a channel.

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

        # US9 additions
        comparison = compare_videos(videos)
        eqs_scores = self._load_eqs_scores(channel_id, videos)
        forecasts = self._load_forecasts(channel_id)
        suggestions = generate_improvement_suggestions(
            videos, eqs_scores=eqs_scores, forecasts=forecasts
        )

        # Save suggestions to storage (T086)
        if suggestions:
            suggestions_data = [s.model_dump() for s in suggestions]
            suggestions_dir = self.data_dir / "processed" / "suggestions"
            write_json(
                suggestions_dir / f"{channel_id}.json", suggestions_data
            )

        # T089: Generate trend chart HTML
        daily_data = self._load_daily_data(channel_id)
        trend_chart_html = ""
        if daily_data:
            from tube_scout.visualization.charts import create_trend_chart_html

            trend_chart_html = create_trend_chart_html(
                daily_data, forecasts=forecasts, title="Daily Views Trend"
            )

        template = self._env.get_template("channel_report.html")
        html = template.render(
            channel=channel,
            videos=videos,
            total_views=total_views,
            insights=insights,
            comparison=comparison,
            suggestions=suggestions,
            forecasts=forecasts,
            trend_chart_html=trend_chart_html,
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

    def _load_eqs_scores(
        self, channel_id: str, videos: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Load EQS quality scores for all videos in the channel.

        Args:
            channel_id: Channel ID.
            videos: List of video dicts to look up scores for.

        Returns:
            List of EQS score dicts.
        """
        scores: list[dict[str, Any]] = []
        for v in videos:
            vid = v.get("video_id", "")
            path = self.data_dir / "processed" / "eqs" / f"{vid}.json"
            data = read_json(path)
            if data:
                scores.append(data)
        return scores

    def _load_forecasts(self, channel_id: str) -> list[dict[str, Any]]:
        """Load forecast data for the channel.

        Args:
            channel_id: Channel ID.

        Returns:
            List of forecast result dicts.
        """
        path = self.data_dir / "processed" / "forecasts" / f"{channel_id}.json"
        data = read_json(path)
        if data is None:
            return []
        return data if isinstance(data, list) else []

    def _load_daily_data(self, channel_id: str) -> list[dict[str, Any]]:
        """Load daily analytics time-series data for the channel.

        Args:
            channel_id: Channel ID.

        Returns:
            List of daily data dicts with 'date' and 'views'.
        """
        path = (
            self.data_dir / "raw" / "analytics" / channel_id / "daily" / "channel.json"
        )
        data = read_json(path)
        if data is None:
            return []
        return data if isinstance(data, list) else []

    def _generate_insights(self, videos: list[dict[str, Any]]) -> list[str]:
        """Generate channel-level insights.

        Args:
            videos: List of video dicts.

        Returns:
            List of insight strings.
        """
        if not videos:
            return ["No videos to analyze."]

        insights = []
        views = [v.get("view_count", 0) for v in videos]
        avg_views = sum(views) / len(views)
        insights.append(f"Average views per video: {avg_views:.0f}")

        durations = [
            v.get("duration_seconds", 0)
            for v in videos
            if v.get("duration_seconds")
        ]
        if durations:
            avg_duration = sum(durations) / len(durations) / 60
            insights.append(
                f"Average video length: {avg_duration:.1f} minutes"
            )

        return insights
