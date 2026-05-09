"""Time-axis match-span visualization for spec 011 nC2 reuse reports.

Renders two horizontal bar rows (video A, video B) with color encoding:
- default match: blue
- baseline_subtracted=True: gray (Layer B)
- whitelisted=True: lightyellow (Layer D)

Falls back to SVG bytes when kaleido is not installed.
"""

import base64

import plotly.graph_objects as go

from tube_scout.models.reuse_v2 import MatchSpan

_COLOR_MATCH = "steelblue"
_COLOR_BASELINE = "gray"
_COLOR_WHITELIST = "lightyellow"


def _span_color(span: MatchSpan) -> str:
    if span.baseline_subtracted:
        return _COLOR_BASELINE
    if span.whitelisted:
        return _COLOR_WHITELIST
    return _COLOR_MATCH


def render(
    spans: list[MatchSpan],
    duration_a: float,
    duration_b: float,
) -> go.Figure:
    """Render time-axis match-span visualization.

    Two horizontal bar rows (video A, video B); each MatchSpan rendered as
    a colored bar at its (start, end) time on each row.

    Args:
        spans: MatchSpan list to visualize.
        duration_a: Total duration of video A in seconds.
        duration_b: Total duration of video B in seconds.

    Returns:
        plotly.graph_objects.Figure with horizontal bar traces.
    """
    fig = go.Figure()

    if not spans:
        fig.update_layout(
            xaxis={"range": [0, max(duration_a, duration_b)]},
            yaxis={"tickvals": [0, 1], "ticktext": ["Video B", "Video A"]},
            height=180,
            margin={"l": 80, "r": 20, "t": 20, "b": 40},
        )
        return fig

    for span in spans:
        color = _span_color(span)
        label = span.matched_text_sample[:40] if span.matched_text_sample else ""

        # Video A row (y=1)
        fig.add_trace(go.Bar(
            x=[span.end_a_seconds - span.start_a_seconds],
            y=["Video A"],
            base=[span.start_a_seconds],
            orientation="h",
            marker={"color": color, "line": {"color": "rgba(0,0,0,0.3)", "width": 0.5}},
            name=label,
            hovertext=label,
            showlegend=False,
        ))

        # Video B row (y=0)
        fig.add_trace(go.Bar(
            x=[span.end_b_seconds - span.start_b_seconds],
            y=["Video B"],
            base=[span.start_b_seconds],
            orientation="h",
            marker={"color": color, "line": {"color": "rgba(0,0,0,0.3)", "width": 0.5}},
            name=label,
            hovertext=label,
            showlegend=False,
        ))

    max_duration = max(duration_a, duration_b)
    fig.update_layout(
        barmode="overlay",
        xaxis={
            "range": [0, max_duration],
            "title": "seconds",
        },
        yaxis={"categoryorder": "array", "categoryarray": ["Video B", "Video A"]},
        height=180,
        width=900,
        margin={"l": 80, "r": 20, "t": 20, "b": 40},
    )

    return fig


def render_to_png_bytes(
    spans: list[MatchSpan],
    duration_a: float,
    duration_b: float,
) -> bytes:
    """Render spans to static image bytes (PNG via kaleido, SVG fallback).

    Args:
        spans: MatchSpan list to visualize.
        duration_a: Total duration of video A in seconds.
        duration_b: Total duration of video B in seconds.

    Returns:
        Image bytes (PNG if kaleido available, SVG otherwise).
    """
    fig = render(spans, duration_a=duration_a, duration_b=duration_b)
    try:
        return fig.to_image(format="png", width=900, height=180)
    except Exception:
        # kaleido not installed — fall back to HTML representation
        return fig.to_html(full_html=False).encode("utf-8")


def render_to_base64_png(
    spans: list[MatchSpan],
    duration_a: float,
    duration_b: float,
) -> str:
    """Render spans to base64-encoded image string for HTML embedding.

    Args:
        spans: MatchSpan list to visualize.
        duration_a: Total duration of video A in seconds.
        duration_b: Total duration of video B in seconds.

    Returns:
        Base64-encoded string of image bytes.
    """
    raw = render_to_png_bytes(spans, duration_a=duration_a, duration_b=duration_b)
    return base64.b64encode(raw).decode("ascii")
