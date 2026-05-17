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
        fig.add_trace(
            go.Bar(
                x=[span.end_a_seconds - span.start_a_seconds],
                y=["Video A"],
                base=[span.start_a_seconds],
                orientation="h",
                marker={
                    "color": color,
                    "line": {"color": "rgba(0,0,0,0.3)", "width": 0.5},
                },
                name=label,
                hovertext=label,
                showlegend=False,
            )
        )

        # Video B row (y=0)
        fig.add_trace(
            go.Bar(
                x=[span.end_b_seconds - span.start_b_seconds],
                y=["Video B"],
                base=[span.start_b_seconds],
                orientation="h",
                marker={
                    "color": color,
                    "line": {"color": "rgba(0,0,0,0.3)", "width": 0.5},
                },
                name=label,
                hovertext=label,
                showlegend=False,
            )
        )

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


def render_pair_alignment_view(
    src_spans: list[MatchSpan],
    tgt_spans: list[MatchSpan],
    src_duration: float,
    tgt_duration: float,
) -> bytes:
    """Render pair alignment view with colored match regions on src/tgt timelines.

    Produces two rows (source, target) with span bars colored by layer attribution.
    Returns static PNG bytes (SVG fallback if kaleido absent).

    Args:
        src_spans: Match spans for source video (positions in source timeline).
        tgt_spans: Match spans for target video (positions in target timeline).
        src_duration: Total duration of source video in seconds.
        tgt_duration: Total duration of target video in seconds.

    Returns:
        Image bytes (PNG if kaleido available, SVG/HTML bytes otherwise).
    """
    fig = go.Figure()

    for span in src_spans:
        color = _span_color(span)
        width = max(span.end_a_seconds - span.start_a_seconds, 0.0)
        fig.add_trace(
            go.Bar(
                x=[width],
                y=["Source"],
                base=[span.start_a_seconds],
                orientation="h",
                marker={
                    "color": color,
                    "line": {"color": "rgba(0,0,0,0.3)", "width": 0.5},
                },
                showlegend=False,
            )
        )

    for span in tgt_spans:
        color = _span_color(span)
        width = max(span.end_b_seconds - span.start_b_seconds, 0.0)
        fig.add_trace(
            go.Bar(
                x=[width],
                y=["Target"],
                base=[span.start_b_seconds],
                orientation="h",
                marker={
                    "color": color,
                    "line": {"color": "rgba(0,0,0,0.3)", "width": 0.5},
                },
                showlegend=False,
            )
        )

    max_duration = max(src_duration, tgt_duration, 1.0)
    fig.update_layout(
        barmode="overlay",
        xaxis={"range": [0, max_duration], "title": "seconds"},
        yaxis={"categoryorder": "array", "categoryarray": ["Target", "Source"]},
        height=160,
        width=900,
        margin={"l": 80, "r": 20, "t": 20, "b": 40},
    )

    try:
        return fig.to_image(format="png", width=900, height=160)
    except Exception:
        return fig.to_html(full_html=False).encode("utf-8")


def render_time_axis_profile(
    spans: list[MatchSpan],
    src_duration: float,
    n_bins: int = 10,
) -> bytes:
    """Render per-bin match density profile chart (I-8 source data).

    Divides source timeline into n_bins equal bins and computes coverage fraction
    for each bin based on span overlap.

    Args:
        spans: Match spans to profile.
        src_duration: Total duration of source video in seconds.
        n_bins: Number of equal-width bins.

    Returns:
        Image bytes (PNG if kaleido available, SVG/HTML bytes otherwise).
    """
    bin_width = src_duration / n_bins if src_duration > 0 else 1.0
    densities = []
    bin_labels = []
    for i in range(n_bins):
        bin_start = i * bin_width
        bin_end = bin_start + bin_width
        covered = 0.0
        for span in spans:
            overlap_start = max(span.start_a_seconds, bin_start)
            overlap_end = min(span.end_a_seconds, bin_end)
            if overlap_end > overlap_start:
                covered += overlap_end - overlap_start
        densities.append(min(covered / bin_width, 1.0))
        bin_labels.append(f"{bin_start:.0f}s")

    fig = go.Figure(
        go.Bar(
            x=bin_labels,
            y=densities,
            marker={"color": "steelblue"},
        )
    )
    fig.update_layout(
        xaxis={"title": "time bin"},
        yaxis={"title": "match density", "range": [0, 1.0]},
        height=200,
        width=900,
        margin={"l": 60, "r": 20, "t": 20, "b": 60},
    )

    try:
        return fig.to_image(format="png", width=900, height=200)
    except Exception:
        return fig.to_html(full_html=False).encode("utf-8")
