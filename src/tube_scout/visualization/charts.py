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


def create_trend_chart_html(
    daily_data: list[dict[str, Any]],
    forecasts: list[dict[str, Any]] | None = None,
    title: str = "Daily Views Trend",
) -> str:
    """Create an embedded HTML div with a daily trend chart and forecast overlay.

    Args:
        daily_data: List of dicts with 'date' (str ISO) and 'views' (int).
        forecasts: Optional forecast dicts with 'date', 'predicted_value',
            'lower_bound', 'upper_bound'.
        title: Chart title.

    Returns:
        HTML string containing the plotly chart div (embeddable in a template).
    """
    if not daily_data:
        return ""

    dates = [d.get("date", "") for d in daily_data]
    views = [d.get("views", 0) for d in daily_data]

    fig = go.Figure()

    fig.add_trace(
        go.Scatter(
            x=dates,
            y=views,
            mode="lines",
            name="Actual",
            line={"color": "#1a73e8", "width": 2},
        )
    )

    if forecasts:
        f_dates = [f.get("date", "") for f in forecasts]
        f_values = [f.get("predicted_value", 0) for f in forecasts]
        f_lower = [f.get("lower_bound", 0) for f in forecasts]
        f_upper = [f.get("upper_bound", 0) for f in forecasts]

        fig.add_trace(
            go.Scatter(
                x=f_dates,
                y=f_values,
                mode="lines",
                name="Forecast",
                line={"color": "#ff6d00", "width": 2, "dash": "dash"},
            )
        )

        # Confidence band
        fig.add_trace(
            go.Scatter(
                x=f_dates + f_dates[::-1],
                y=f_upper + f_lower[::-1],
                fill="toself",
                fillcolor="rgba(255, 109, 0, 0.1)",
                line={"color": "rgba(255,255,255,0)"},
                name="95% Confidence",
                showlegend=True,
            )
        )

    fig.update_layout(
        title=title,
        xaxis_title="Date",
        yaxis_title="Views",
        template="plotly_white",
        height=350,
        margin={"l": 50, "r": 20, "t": 40, "b": 40},
    )

    return fig.to_html(full_html=False, include_plotlyjs="cdn")
