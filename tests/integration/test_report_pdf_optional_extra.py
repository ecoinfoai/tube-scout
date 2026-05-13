"""T079 RED → GREEN — weasyprint ImportError actionable message test (spec 013)."""
import sys
from pathlib import Path
from unittest.mock import patch

import pytest


def test_render_pdf_raises_import_error_with_actionable_message(tmp_path: Path) -> None:
    """_render_pdf raises ImportError with 'uv sync --extra pdf' message when weasyprint absent."""
    from tube_scout.reporting.professor_nc2 import _render_pdf

    pdf_path = tmp_path / "test.pdf"

    with patch.dict(sys.modules, {"weasyprint": None}):
        with pytest.raises(ImportError) as exc_info:
            _render_pdf("<html><body>test</body></html>", pdf_path)

    assert "uv sync --extra pdf" in str(exc_info.value), (
        f"ImportError message must contain 'uv sync --extra pdf'. Got: {exc_info.value}"
    )
