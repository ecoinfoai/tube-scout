"""Jupyter Notebook export for video analysis reports (T059a)."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import nbformat


class VideoNotebookExporter:
    """Export video analysis data as a Jupyter Notebook."""

    def export(
        self,
        video: dict[str, Any],
        retention: dict[str, Any] | None,
        segments: list[dict[str, Any]] | None,
        output_dir: Path,
    ) -> Path:
        """Generate a Jupyter Notebook for a video analysis.

        Args:
            video: Video metadata dict.
            retention: Retention analysis results.
            segments: Transcript segments.
            output_dir: Output directory.

        Returns:
            Path to the generated .ipynb file.
        """
        nb = nbformat.v4.new_notebook()
        nb.metadata["kernelspec"] = {
            "display_name": "Python 3",
            "language": "python",
            "name": "python3",
        }

        cells: list[Any] = []

        # Title cell
        video_id = video.get("video_id", "unknown")
        title = video.get("title", video_id)
        cells.append(
            nbformat.v4.new_markdown_cell(
                f"# Video Analysis: {title}\n\n"
                f"**Video ID:** `{video_id}`  \n"
                f"**Generated:** {datetime.now(UTC).isoformat()}"
            )
        )

        # Video metrics cell
        cells.append(nbformat.v4.new_markdown_cell("## Video Metrics"))
        cells.append(
            nbformat.v4.new_code_cell(
                f"video = {_format_dict(video)}\n"
                "print(f\"Duration: {video.get('duration_seconds', 0) // 60} min\")\n"
                "print(f\"Views: {video.get('view_count', 0):,}\")\n"
                "print(f\"Likes: {video.get('like_count', 0):,}\")"
            )
        )

        # Retention analysis
        if retention:
            cells.append(nbformat.v4.new_markdown_cell("## Retention Analysis"))
            hotspots = retention.get("hotspots", [])
            skip_zones = retention.get("skip_zones", [])
            cells.append(
                nbformat.v4.new_code_cell(
                    _build_retention_chart_code(hotspots, skip_zones)
                )
            )

        # Segments
        if segments:
            cells.append(nbformat.v4.new_markdown_cell("## Transcript Segments"))
            cells.append(
                nbformat.v4.new_code_cell(_build_segments_table_code(segments))
            )

        nb.cells = cells
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"{video_id}.ipynb"
        nbformat.write(nb, str(output_path))
        return output_path


def _format_dict(d: dict[str, Any]) -> str:
    """Format a dict as a Python literal string.

    Args:
        d: Dictionary to format.

    Returns:
        String representation.
    """
    import json

    return json.dumps(d, indent=2, default=str)


def _build_retention_chart_code(
    hotspots: list[dict[str, Any]],
    skip_zones: list[dict[str, Any]],
) -> str:
    """Build plotly retention chart code cell.

    Args:
        hotspots: List of hotspot dicts.
        skip_zones: List of skip zone dicts.

    Returns:
        Python code string for the cell.
    """
    import json

    return (
        "import plotly.graph_objects as go\n\n"
        f"hotspots = {json.dumps(hotspots, default=str)}\n"
        f"skip_zones = {json.dumps(skip_zones, default=str)}\n\n"
        "fig = go.Figure()\n"
        "if hotspots:\n"
        "    fig.add_trace(go.Scatter(\n"
        "        x=[h['elapsed_ratio'] for h in hotspots],\n"
        "        y=[h['audience_watch_ratio'] for h in hotspots],\n"
        "        mode='markers',\n"
        "        name='Rewatch Hotspots',\n"
        "        marker=dict(color='red', size=10),\n"
        "    ))\n"
        "if skip_zones:\n"
        "    fig.add_trace(go.Scatter(\n"
        "        x=[s['elapsed_ratio'] for s in skip_zones],\n"
        "        y=[s['audience_watch_ratio'] for s in skip_zones],\n"
        "        mode='markers',\n"
        "        name='Skip Zones',\n"
        "        marker=dict(color='blue', size=10),\n"
        "    ))\n"
        "fig.update_layout(\n"
        "    title='Retention Analysis',\n"
        "    xaxis_title='Video Position (ratio)',\n"
        "    yaxis_title='Watch Ratio',\n"
        ")\n"
        "fig.show()"
    )


def _build_segments_table_code(
    segments: list[dict[str, Any]],
) -> str:
    """Build segment summary table code cell.

    Args:
        segments: List of segment dicts.

    Returns:
        Python code string for the cell.
    """
    import json

    return (
        "import pandas as pd\n\n"
        f"segments = {json.dumps(segments, default=str)}\n"
        "df = pd.DataFrame(segments)\n"
        "cols = ['segment_index', 'title', 'start_seconds', "
        "'end_seconds', 'difficulty_score']\n"
        "available = [c for c in cols if c in df.columns]\n"
        "df[available]"
    )
