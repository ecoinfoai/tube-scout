"""Unit tests — ASR ImportError actionable message (spec 013 T044 RED).

FR-016: faster-whisper not installed → ImportError with 'uv sync --extra asr' message.
Module does not exist yet — all tests should fail at import.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest


def test_transcribe_audio_raises_importerror_with_actionable_message(
    tmp_path: Path,
) -> None:
    """transcribe_audio raises ImportError with 'uv sync --extra asr' when faster-whisper missing."""
    from tube_scout.services.asr import transcribe_audio

    wav_path = tmp_path / "test.wav"
    wav_path.write_bytes(b"\x00" * 100)

    with patch.dict("sys.modules", {"faster_whisper": None}):
        with pytest.raises(ImportError) as exc_info:
            transcribe_audio(wav_path)

    message = str(exc_info.value)
    assert "uv sync --extra asr" in message, (
        f"ImportError message must contain 'uv sync --extra asr', got: {message!r}"
    )


def test_transcribe_audio_importerror_mentions_faster_whisper(
    tmp_path: Path,
) -> None:
    """ImportError message must mention 'faster-whisper' so user knows what to install."""
    from tube_scout.services.asr import transcribe_audio

    wav_path = tmp_path / "test.wav"
    wav_path.write_bytes(b"\x00" * 100)

    with patch.dict("sys.modules", {"faster_whisper": None}):
        with pytest.raises(ImportError) as exc_info:
            transcribe_audio(wav_path)

    message = str(exc_info.value)
    assert "faster-whisper" in message, (
        f"ImportError message must mention 'faster-whisper', got: {message!r}"
    )
