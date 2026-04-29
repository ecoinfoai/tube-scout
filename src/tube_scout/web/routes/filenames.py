"""Filename slug builder + RFC-5987 Content-Disposition encoder (T017 helper).

Used by ``routes/results.py`` to render ``Content-Disposition`` headers for
the 5 download artifact kinds. Korean filename support is essential — the
operator's job_id slug includes department display name + professor + course
which are Hangul, so the response must emit ``filename*=UTF-8''<encoded>``
per RFC 5987 plus an ASCII fallback ``filename=`` for older clients.
"""

from __future__ import annotations

import re
import urllib.parse
from typing import Final

KIND_EXTENSIONS: Final[dict[str, tuple[str, str]]] = {
    # kind → (extension, disposition)
    "v1v3-html": ("html", "inline"),
    "v1v3-pdf": ("pdf", "attachment"),
    "v1v3-excel": ("xlsx", "attachment"),
    "reuse-html": ("html", "inline"),
    "reuse-excel": ("xlsx", "attachment"),
}

KIND_CONTENT_TYPES: Final[dict[str, str]] = {
    "v1v3-html": "text/html; charset=utf-8",
    "v1v3-pdf": "application/pdf",
    "v1v3-excel": (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    ),
    "reuse-html": "text/html; charset=utf-8",
    "reuse-excel": (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    ),
}

_TRAVERSAL_RE = re.compile(r"[\\/]+|\.\.")


def _sanitize_part(value: str) -> str:
    """Strip path-traversal sequences (``/``, ``\\``, ``..``) from a slug part."""
    cleaned = _TRAVERSAL_RE.sub("", value or "")
    return cleaned.strip()


def build_slug(
    *,
    display_name: str,
    professor_name: str,
    course_name: str,
    period_start: str,
    period_end: str,
) -> str:
    """Return ``{display_name}_{professor}_{course}_{start}_{end}``.

    Path-traversal characters are stripped — operators routinely re-use the
    slug as a Content-Disposition filename and a directory hint, so any
    ``/``, ``\\``, or ``..`` substring must not survive.
    """
    parts = [
        _sanitize_part(display_name),
        _sanitize_part(professor_name),
        _sanitize_part(course_name),
        _sanitize_part(period_start),
        _sanitize_part(period_end),
    ]
    return "_".join(parts)


def _ascii_fallback(filename: str) -> str:
    """Return an ASCII-only fallback for the ``filename=`` parameter.

    Non-ASCII characters are replaced with ``_`` so even pre-RFC-5987 clients
    can save the file under a deterministic name.
    """
    return "".join(ch if ord(ch) < 0x80 else "_" for ch in filename)


def content_disposition(*, slug: str, kind: str) -> str:
    """Return a ``Content-Disposition`` header value for ``kind``.

    Args:
        slug: Slug from :func:`build_slug` (Korean characters allowed).
        kind: One of the 5 keys in :data:`KIND_EXTENSIONS`.

    Returns:
        Header value beginning with ``inline`` or ``attachment`` followed by
        ``filename=<ascii>`` and ``filename*=UTF-8''<percent-encoded>``.

    Raises:
        ValueError: If ``kind`` is not in the whitelist.
    """
    if kind not in KIND_EXTENSIONS:
        raise ValueError(f"unknown kind: {kind!r}")
    ext, disposition = KIND_EXTENSIONS[kind]
    # Filename uses the underscore-flavoured kind suffix (e.g. v1v3-html →
    # ``_v1v3.html``) — operators recognise the v1v3/reuse split by the
    # extension + suffix rather than the routing-only dash form.
    suffix = kind.split("-")[0]
    name = f"{slug}_{suffix}.{ext}"
    encoded = urllib.parse.quote(name, safe="")
    ascii_fallback = _ascii_fallback(name).replace('"', "")
    return (
        f'{disposition}; filename="{ascii_fallback}"; '
        f"filename*=UTF-8''{encoded}"
    )


def content_type_for(kind: str) -> str:
    """Return the MIME type for ``kind`` (whitelist enforced)."""
    if kind not in KIND_CONTENT_TYPES:
        raise ValueError(f"unknown kind: {kind!r}")
    return KIND_CONTENT_TYPES[kind]
