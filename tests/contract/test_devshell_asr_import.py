"""Contract test — faster-whisper import smoke test (spec 013 T004 / B-12 / B-13)."""

import importlib

import pytest


def test_faster_whisper_import_succeeds() -> None:
    """faster-whisper must import after `uv sync --extra asr`.

    GREEN requires the [asr] optional extra to have been installed.
    """
    pytest.importorskip("faster_whisper", reason="Install via: uv sync --extra asr")
    module = importlib.import_module("faster_whisper")
    assert hasattr(module, "WhisperModel"), (
        "faster_whisper module is missing the WhisperModel symbol — "
        "verify pyproject.toml [asr] extra and `uv sync --extra asr` succeeded."
    )
