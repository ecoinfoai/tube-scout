"""Plotly chart generation for tube-scout."""

from pathlib import Path
from typing import Any

import plotly.graph_objects as go


def create_retention_chart(
    retention: list[dict[str, Any]],
    hotspots: list[dict[str, Any]],
    skip_zones: list[dict[str, Any]],
    video_id: str,
    output_path: Path,
) -> Path:
    """Create a retention chart with highlighted hotspots and skip zones.

    Args:
        retention: Full retention data points.
        hotspots: Detected rewatch hotspot data points.
        skip_zones: Detected skip zone data points.
        video_id: Video ID for the chart title.
        output_path: Path to save the HTML chart.

    Returns:
        Path to the saved HTML file.
    """
    x = [r["elapsed_ratio"] for r in retention]
    y = [r["audience_watch_ratio"] for r in retention]

    fig = go.Figure()

    # Main retention line
    fig.add_trace(
        go.Scatter(
            x=x,
            y=y,
            mode="lines",
            name="Retention",
            line={"color": "blue", "width": 2},
        )
    )

    # Hotspot markers
    if hotspots:
        hx = [h["elapsed_ratio"] for h in hotspots]
        hy = [h["audience_watch_ratio"] for h in hotspots]
        fig.add_trace(
            go.Scatter(
                x=hx,
                y=hy,
                mode="markers",
                name="Rewatch Hotspot",
                marker={"color": "red", "size": 10, "symbol": "triangle-up"},
            )
        )

    # Skip zone markers
    if skip_zones:
        sx = [s["elapsed_ratio"] for s in skip_zones]
        sy = [s["audience_watch_ratio"] for s in skip_zones]
        fig.add_trace(
            go.Scatter(
                x=sx,
                y=sy,
                mode="markers",
                name="Skip Zone",
                marker={"color": "gray", "size": 10, "symbol": "triangle-down"},
            )
        )

    fig.update_layout(
        title=f"Audience Retention: {video_id}",
        xaxis_title="Video Progress",
        yaxis_title="Watch Ratio",
        xaxis={"tickformat": ".0%"},
        yaxis={"range": [0, max(y) * 1.1] if y else [0, 1]},
        template="plotly_white",
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.write_html(str(output_path))
    return output_path
