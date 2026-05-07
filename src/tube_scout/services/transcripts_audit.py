"""Diagnostic audit CSV for transcript collection misses.

Spec 009 FR-016 / Phase 6 (US4). When `collect transcripts` cannot
recover a transcript for a video (private + Captions API failed,
disabled by uploader, etc.), each miss is classified and written to
``<project>/01_collect/transcripts_audit.csv`` so the operator can
diagnose without scrolling through verbose tracebacks.

Classification rules — research.md R5 distillation:

- ``private_no_captions_api``: video is private/unlisted AND Captions API
  client is missing or returned no segments. Hint: register the channel
  via ``tube-scout auth --channel <alias>`` and re-run.
- ``transcripts_disabled``: uploader disabled transcripts. Hint: contact
  uploader; no programmatic fix.
- ``no_caption_track``: public video but neither manual nor ASR caption
  track exists. Hint: ASR may still be processing if recently uploaded.
- ``api_error``: any other error from youtube-transcript-api or Captions
  API. Hint: retry; check API quota.
- ``unknown``: classification did not match any rule. Hint: re-run with
  ``--verbose`` to surface the underlying exception.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

AUDIT_HEADER: tuple[str, ...] = (
    "video_id",
    "title",
    "published_at",
    "privacy_status",
    "classification",
    "hint",
)

ALLOWED_CLASSIFICATIONS: frozenset[str] = frozenset(
    {
        "private_no_captions_api",
        "transcripts_disabled",
        "no_caption_track",
        "api_error",
        "unknown",
    }
)


def classify_miss(
    primary_error: BaseException | None,
    fallback_error: BaseException | None,
    video_meta: dict[str, Any],
) -> tuple[str, str]:
    """Classify why a transcript miss happened and produce a recovery hint.

    Args:
        primary_error: Exception raised by the youtube-transcript-api
            primary path. ``None`` if the primary path succeeded but the
            fallback was still attempted (rare).
        fallback_error: Exception raised by the Captions API fallback path,
            or ``None`` if no fallback was attempted.
        video_meta: Video metadata dict — at minimum ``video_id``;
            optionally ``privacy_status`` and ``title``.

    Returns:
        ``(classification, hint)`` tuple. Both strings are non-empty;
        ``classification`` is one of :data:`ALLOWED_CLASSIFICATIONS`.
    """
    privacy = (video_meta.get("privacy_status") or "").lower()
    primary_name = type(primary_error).__name__ if primary_error else ""
    fallback_name = type(fallback_error).__name__ if fallback_error else ""

    if "TranscriptsDisabled" in primary_name:
        return (
            "transcripts_disabled",
            "Uploader disabled captions; no programmatic recovery.",
        )

    if privacy in {"private", "unlisted"} and (
        fallback_error is not None or fallback_name == ""
    ):
        return (
            "private_no_captions_api",
            "Video is non-public; register channel via 'tube-scout auth"
            " --channel <alias>' and re-run with that alias.",
        )

    if "NoTranscriptFound" in primary_name and not fallback_error:
        return (
            "no_caption_track",
            "No manual or ASR caption track found. ASR may still be"
            " processing if the video was uploaded recently.",
        )

    if primary_error is not None or fallback_error is not None:
        cause = primary_name or fallback_name or "unknown"
        return (
            "api_error",
            f"API error ({cause}); retry, check quota, or run with --verbose.",
        )

    return (
        "unknown",
        "No classifier rule matched; re-run with --verbose to surface the cause.",
    )


def write_audit_csv(rows: list[dict[str, Any]], path: Path) -> None:
    """Write audit rows to ``path`` with the canonical header.

    Excel-injection guard: cells starting with ``=``, ``+``, ``-``, ``@``
    are prefixed with a single quote per OWASP guidance. Newlines and
    commas are handled by the csv module's default quoting.

    Args:
        rows: List of dicts, each containing keys from :data:`AUDIT_HEADER`.
            Missing keys are written as empty strings.
        path: Destination file path. Parent dirs are created if missing.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(AUDIT_HEADER)
        for row in rows:
            writer.writerow(
                _sanitize_cell(row.get(field, "")) for field in AUDIT_HEADER
            )


def _sanitize_cell(value: Any) -> str:
    """Render value as string and neutralize Excel-injection prefixes."""
    text = "" if value is None else str(value)
    if text and text[0] in {"=", "+", "-", "@"}:
        return "'" + text
    return text
