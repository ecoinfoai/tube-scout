"""Spec 013 T004 — contract smoke test: faster-whisper [asr] extra importability.

GREEN requires: uv sync --extra asr (installs faster-whisper + CTranslate2 backend).
Without the extra the test is skipped with an actionable message.
"""

from __future__ import annotations

import pytest


def test_faster_whisper_import_succeeds() -> None:
    """Assert that faster_whisper.WhisperModel is importable after uv sync --extra asr."""
    # GREEN requires: uv sync --extra asr
    fw = pytest.importorskip(
        "faster_whisper",
        reason="faster-whisper not installed — run: uv sync --extra asr",
    )
    assert hasattr(fw, "WhisperModel"), (
        "faster_whisper.WhisperModel not found; package may be partially installed"
    )
