"""T073 RED — SC-007 report tone regression test.

Generates a minimal professor_nC2_report HTML and verifies:
- Definitive-verdict tokens ("재활용 확정", "위반", "표절", "복제") are absent.
- Reservation-form tokens ("의심 근거", "검토 우선순위 상위", "주의 필요") are present in the template.
"""
import re
from pathlib import Path

_FORBIDDEN_TOKENS = ["재활용 확정", "위반", "표절", "복제"]
_REQUIRED_TOKENS = ["의심 근거", "검토 우선순위 상위", "주의 필요"]


def _read_template() -> str:
    template_path = (
        Path(__file__).parent.parent.parent
        / "src" / "tube_scout" / "reporting" / "templates" / "professor_nC2_report.html"
    )
    return template_path.read_text(encoding="utf-8")


def _strip_jinja_comments(content: str) -> str:
    """Remove Jinja2 {# ... #} comment blocks before tone checking."""
    return re.sub(r"\{#.*?#\}", "", content, flags=re.DOTALL)


def test_template_contains_no_forbidden_verdict_tokens() -> None:
    """SC-007: template body (outside comments) must not contain definitive-verdict tokens."""
    content = _strip_jinja_comments(_read_template())
    for token in _FORBIDDEN_TOKENS:
        assert token not in content, (
            f"SC-007 violated: forbidden verdict token found in template body: '{token}'"
        )


def test_template_contains_required_reservation_tokens() -> None:
    """SC-007: template source must contain all reservation-form tokens."""
    content = _read_template()
    for token in _REQUIRED_TOKENS:
        assert token in content, (
            f"SC-007 violated: required reservation token missing from template: '{token}'"
        )


def test_rendered_html_contains_no_forbidden_verdict_tokens(tmp_path: Path) -> None:
    """SC-007 regression: rendered HTML output must not contain definitive-verdict tokens."""

    from tube_scout.reporting.professor_nc2 import (
        AppendixThresholds,
        render_professor_nc2_report,
    )
    from tube_scout.storage.content_db import (
        ContentDB,
        _ensure_v4,
        migrate_to_v2,
        migrate_to_v3,
    )

    db_path = tmp_path / "reuse.db"
    ContentDB(db_path).close()
    migrate_to_v2(db_path)
    migrate_to_v3(db_path)
    _ensure_v4(db_path)

    db = ContentDB(db_path)
    try:
        result = render_professor_nc2_report(
            professor="test-prof",
            channel_alias="test-channel",
            db=db,
            output_dir=tmp_path,
            output_format="html",
            appendix_thresholds=AppendixThresholds(),
        )
    finally:
        db.close()

    assert result.html_path is not None
    html_content = result.html_path.read_text(encoding="utf-8")
    for token in _FORBIDDEN_TOKENS:
        assert token not in html_content, (
            f"SC-007 violated in rendered HTML: forbidden token '{token}'"
        )
