"""Bundle report generator for combined PDF output."""

import logging
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader

from tube_scout.models.video_filter import VideoFilter
from tube_scout.services.video_filter_service import VideoFilterService
from tube_scout.storage.json_store import read_json

logger = logging.getLogger(__name__)


class BundleReportGenerator:
    """Generate combined PDF bundle reports from filtered videos.

    Args:
        data_dir: Root data directory containing raw and processed data.
    """

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
        video_filter: VideoFilter,
        channel_id: str,
        output_path: Path,
        sort_by: str = "date",
        title: str | None = None,
    ) -> Path:
        """Generate an HTML bundle report for filtered videos.

        Args:
            video_filter: Filter criteria for selecting videos.
            channel_id: YouTube channel ID.
            output_path: Path for the output HTML file.
            sort_by: Sort order — 'date', 'course', or 'views'.
            title: Custom report title. Auto-generated if None.

        Returns:
            Path to the generated HTML file.

        Raises:
            ValueError: If no videos match the filter.
        """
        videos_meta = self._load_videos_meta(channel_id)
        filtered = VideoFilterService.filter_videos(videos_meta, video_filter)

        if not filtered:
            raise ValueError("No videos matching the specified filters")

        filtered = VideoFilterService.sort_videos(filtered, sort_by)

        video_data = []
        for meta in filtered:
            vid_id = meta["video_id"]
            video_data.append({
                "meta": meta,
                "retention": self._load_retention(vid_id),
                "segments": self._load_segments(vid_id),
            })

        report_title = title or self._auto_title(video_filter, channel_id)
        filter_desc = self._filter_description(video_filter)
        summary = self._compute_summary(filtered)

        template = self._env.get_template("bundle_report.html")
        html = template.render(
            title=report_title,
            channel_id=channel_id,
            filter_description=filter_desc,
            videos=video_data,
            summary=summary,
            generated_at=datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
        )

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(html, encoding="utf-8")
        return output_path

    def render_pdf(self, html_path: Path) -> Path | None:
        """Convert HTML to PDF using weasyprint.

        Args:
            html_path: Path to the HTML file.

        Returns:
            Path to the generated PDF, or None if weasyprint is unavailable.
        """
        try:
            from weasyprint import HTML  # type: ignore[import-untyped]
        except (ImportError, OSError):
            return None

        pdf_path = html_path.with_suffix(".pdf")
        HTML(filename=str(html_path)).write_pdf(str(pdf_path))
        return pdf_path

    def generate_from_html(
        self,
        html_dir: Path,
        video_filter: VideoFilter,
        channel_id: str,
        output_path: Path,
        sort_by: str = "date",
        title: str | None = None,
    ) -> Path:
        """Generate a bundle report from existing HTML report files.

        Args:
            html_dir: Directory containing existing {video_id}.html files.
            video_filter: Filter criteria for selecting videos.
            channel_id: YouTube channel ID.
            output_path: Path for the output HTML file.
            sort_by: Sort order — 'date', 'course', or 'views'.
            title: Custom report title. Auto-generated if None.

        Returns:
            Path to the generated HTML file.

        Raises:
            ValueError: If no videos match the filter or no HTML files found.
        """
        videos_meta = self._load_videos_meta(channel_id)
        filtered = VideoFilterService.filter_videos(videos_meta, video_filter)

        if not filtered:
            raise ValueError("No videos matching the specified filters")

        filtered = VideoFilterService.sort_videos(filtered, sort_by)

        skipped: list[str] = []
        video_data: list[dict[str, Any]] = []
        for meta in filtered:
            vid_id = meta["video_id"]
            html_file = html_dir / f"{vid_id}.html"
            try:
                if not html_file.exists():
                    skipped.append(vid_id)
                    logger.warning("HTML file not found for %s, skipping", vid_id)
                    continue
                raw_html = html_file.read_text(encoding="utf-8")
                body = self._extract_html_body(raw_html)
                if not body:
                    skipped.append(vid_id)
                    logger.warning("Could not parse body from %s, skipping", html_file)
                    continue
            except (OSError, UnicodeDecodeError) as exc:
                skipped.append(vid_id)
                logger.warning("Could not read %s: %s, skipping", html_file, exc)
                continue

            video_data.append({
                "meta": meta,
                "body_html": body,
            })

        if not video_data:
            raise ValueError(
                "No videos with available HTML files matching the specified filters"
            )

        report_title = title or self._auto_title(video_filter, channel_id)
        filter_desc = self._filter_description(video_filter)
        summary = self._compute_summary(filtered)

        template = self._env.get_template("bundle_from_html.html")
        html = template.render(
            title=report_title,
            channel_id=channel_id,
            filter_description=filter_desc,
            videos=video_data,
            summary=summary,
            skipped=skipped,
            generated_at=datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
        )

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(html, encoding="utf-8")
        return output_path

    @staticmethod
    def _extract_html_body(html_content: str) -> str:
        """Extract content between <body> and </body> tags.

        Args:
            html_content: Full HTML document string.

        Returns:
            Inner HTML of the body element, or empty string if not found.
        """
        class _BodyExtractor(HTMLParser):
            def __init__(self) -> None:
                super().__init__()
                self._in_body = False
                self._depth = 0
                self._parts: list[str] = []

            def handle_starttag(
                self, tag: str, attrs: list[tuple[str, str | None]]
            ) -> None:
                if tag == "body":
                    self._in_body = True
                    self._depth = 1
                    return
                if self._in_body:
                    self._depth += 1
                    attr_str = ""
                    for name, val in attrs:
                        if val is None:
                            attr_str += f" {name}"
                        else:
                            attr_str += f' {name}="{val}"'
                    self._parts.append(f"<{tag}{attr_str}>")

            def handle_endtag(self, tag: str) -> None:
                if tag == "body" and self._in_body:
                    self._in_body = False
                    return
                if self._in_body:
                    self._depth -= 1
                    self._parts.append(f"</{tag}>")

            def handle_data(self, data: str) -> None:
                if self._in_body:
                    self._parts.append(data)

        parser = _BodyExtractor()
        parser.feed(html_content)
        return "".join(parser._parts)

    def _load_videos_meta(self, channel_id: str) -> list[dict[str, Any]]:
        """Load videos metadata for a channel.

        Args:
            channel_id: YouTube channel ID.

        Returns:
            List of video metadata dicts.
        """
        videos_path = (
            self.data_dir / "raw" / "channels" / channel_id / "videos_meta.json"
        )
        videos = read_json(videos_path)
        if not videos:
            return []
        return videos if isinstance(videos, list) else videos.get("videos", [])

    def _load_retention(self, video_id: str) -> dict[str, Any] | None:
        """Load retention analysis for a video.

        Args:
            video_id: YouTube video ID.

        Returns:
            Retention data dict, or None if not available.
        """
        path = self.data_dir / "processed" / "retention" / f"{video_id}.json"
        return read_json(path)

    def _load_segments(self, video_id: str) -> list[dict[str, Any]] | None:
        """Load transcript segments for a video.

        Args:
            video_id: YouTube video ID.

        Returns:
            List of segment dicts, or None if not available.
        """
        path = self.data_dir / "processed" / "segments" / f"{video_id}.json"
        return read_json(path)


    @staticmethod
    def _compute_summary(videos: list[dict[str, Any]]) -> dict[str, Any]:
        """Compute aggregate statistics for filtered videos.

        Args:
            videos: List of video metadata dicts.

        Returns:
            Dict with video_count, total_duration_minutes, avg_views, total_likes.
        """
        count = len(videos)
        total_duration = sum(v.get("duration_seconds", 0) for v in videos)
        total_views = sum(v.get("view_count", 0) for v in videos)
        total_likes = sum(v.get("like_count", 0) for v in videos)
        return {
            "video_count": count,
            "total_duration_minutes": total_duration // 60,
            "avg_views": total_views // count if count else 0,
            "total_likes": total_likes,
        }

    @staticmethod
    def _auto_title(video_filter: VideoFilter, channel_id: str) -> str:
        """Generate automatic report title from filter and channel.

        Args:
            video_filter: The filter used.
            channel_id: YouTube channel ID.

        Returns:
            Auto-generated title string.
        """
        parts = ["Bundle Report"]
        if video_filter.keyword:
            parts.append(f"— {video_filter.keyword}")
        if video_filter.published_after or video_filter.published_before:
            date_range = ""
            if video_filter.published_after:
                date_range += str(video_filter.published_after)
            date_range += " ~ "
            if video_filter.published_before:
                date_range += str(video_filter.published_before)
            parts.append(f"({date_range})")
        return " ".join(parts)

    @staticmethod
    def _filter_description(video_filter: VideoFilter) -> str:
        """Build a human-readable description of the filter criteria.

        Args:
            video_filter: The filter used.

        Returns:
            Description string.
        """
        parts: list[str] = []
        if video_filter.keyword:
            parts.append(f"Keyword: {video_filter.keyword}")
        if video_filter.published_after:
            parts.append(f"From: {video_filter.published_after}")
        if video_filter.published_before:
            parts.append(f"To: {video_filter.published_before}")
        if video_filter.video_ids:
            parts.append(f"IDs: {', '.join(video_filter.video_ids)}")
        return " | ".join(parts) if parts else "All videos"
