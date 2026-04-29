"""Tests for filename slug + RFC-5987 Content-Disposition encoding (T017 RED).

Covers:
- Slug builder ``{display_name}_{professor}_{course}_{period_start}_{period_end}``
- Korean characters preserved in the slug (raw form for routing only)
- RFC-5987 ``Content-Disposition`` value: ASCII fallback ``filename=`` plus
  UTF-8 ``filename*=`` parameter so Korean filenames render correctly in
  Chrome/Firefox/Edge regardless of OS locale
- Disposition type: ``inline`` for HTML, ``attachment`` for PDF/Excel
- Path traversal characters (``/``, ``\\``, ``..``) sanitized in slug

Targets ``tube_scout.web.routes.results`` (or a helper module) — pending T055.
The helper is currently expected to live at ``tube_scout.web.routes.filenames``
to keep the route handler small.
"""

from __future__ import annotations

import urllib.parse

import pytest


def test_slug_concatenates_fields_with_underscores() -> None:
    from tube_scout.web.routes import filenames

    slug = filenames.build_slug(
        display_name="물리치료과",
        professor_name="홍길동",
        course_name="해부생리학",
        period_start="2026-03-01",
        period_end="2026-04-30",
    )
    assert slug == "물리치료과_홍길동_해부생리학_2026-03-01_2026-04-30"


def test_slug_strips_path_traversal_chars() -> None:
    from tube_scout.web.routes import filenames

    slug = filenames.build_slug(
        display_name="bad/../seg",
        professor_name="홍\\길동",
        course_name="..",
        period_start="2026-03-01",
        period_end="2026-04-30",
    )
    assert "/" not in slug
    assert "\\" not in slug
    assert ".." not in slug


def test_content_disposition_html_inline() -> None:
    from tube_scout.web.routes import filenames

    cd = filenames.content_disposition(
        slug="물리치료과_홍길동_해부생리학_2026-03-01_2026-04-30",
        kind="v1v3-html",
    )
    assert cd.startswith("inline")
    assert "filename*=UTF-8''" in cd
    encoded = urllib.parse.quote(
        "물리치료과_홍길동_해부생리학_2026-03-01_2026-04-30_v1v3.html"
    )
    assert encoded in cd


def test_content_disposition_pdf_attachment() -> None:
    from tube_scout.web.routes import filenames

    cd = filenames.content_disposition(
        slug="물리치료과_홍길동_해부생리학_2026-03-01_2026-04-30",
        kind="v1v3-pdf",
    )
    assert cd.startswith("attachment")
    assert "filename*=UTF-8''" in cd
    assert ".pdf" in cd


def test_content_disposition_excel_attachment() -> None:
    from tube_scout.web.routes import filenames

    cd = filenames.content_disposition(
        slug="물리치료과_홍길동_해부생리학_2026-03-01_2026-04-30",
        kind="v1v3-excel",
    )
    assert cd.startswith("attachment")
    assert ".xlsx" in cd


def test_content_disposition_reuse_kinds() -> None:
    from tube_scout.web.routes import filenames

    html = filenames.content_disposition(slug="x", kind="reuse-html")
    excel = filenames.content_disposition(slug="x", kind="reuse-excel")
    assert html.startswith("inline")
    assert excel.startswith("attachment")


def test_content_disposition_unknown_kind_rejected() -> None:
    from tube_scout.web.routes import filenames

    with pytest.raises(ValueError):
        filenames.content_disposition(slug="x", kind="unknown")


def test_content_disposition_includes_ascii_fallback() -> None:
    """RFC 5987: clients lacking ``filename*`` support fall back to ASCII
    ``filename=``. The ASCII fallback should be present and never include raw
    Hangul (which would be unreliable across browsers)."""
    from tube_scout.web.routes import filenames

    cd = filenames.content_disposition(
        slug="물리치료과_홍길동_해부생리학_2026-03-01_2026-04-30",
        kind="v1v3-pdf",
    )
    assert "filename=" in cd
    # ASCII fallback portion comes before ``filename*=``.
    fallback_part = cd.split("filename*=")[0]
    # No raw Hangul in the ASCII fallback.
    for ch in fallback_part:
        assert ord(ch) < 0x80, f"non-ASCII {ch!r} in fallback: {fallback_part!r}"
