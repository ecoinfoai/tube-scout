"""T054 RED — ASR integration with monkeypatched WhisperModel.

Uses a fake WhisperModel that returns deterministic segments.
Silent 1-second WAV fixture created via soundfile/struct (no ffmpeg needed).
"""
import struct
import wave
from pathlib import Path

import pytest

pytestmark = pytest.mark.slow


def _write_silent_wav(path: Path, duration_s: float = 1.0, sample_rate: int = 16000) -> None:
    """Write a silent 16-bit mono PCM WAV to path."""
    n_samples = int(duration_s * sample_rate)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(struct.pack(f"<{n_samples}h", *([0] * n_samples)))


class _FakeSegment:
    def __init__(self, start: float, end: float, text: str, compression_ratio: float = 1.0, no_speech_prob: float = 0.0):
        self.start = start
        self.end = end
        self.text = text
        self.compression_ratio = compression_ratio
        self.no_speech_prob = no_speech_prob
        self.words = None


class _FakeWhisperModel:
    def __init__(self, *args, **kwargs):
        pass

    def transcribe(self, audio_path, **kwargs):
        segments = [
            _FakeSegment(0.0, 0.5, "안녕하세요"),
            _FakeSegment(0.5, 1.0, "반갑습니다"),
        ]
        info = type("Info", (), {"language": "ko", "duration": 1.0})()
        return iter(segments), info


def test_transcribe_audio_returns_segments(tmp_path: Path, monkeypatch) -> None:
    """transcribe_audio with mocked WhisperModel returns expected segments."""
    import tube_scout.services.asr as asr_module
    monkeypatch.setattr(asr_module, "_load_model", lambda *a, **k: _FakeWhisperModel())

    wav_path = tmp_path / "test_silent.wav"
    _write_silent_wav(wav_path)

    from tube_scout.services.asr import transcribe_audio

    result = transcribe_audio(wav_path, model_size="large-v3", compute_type="int8_float16", device="cpu", device_index=0)

    assert len(result.segments) == 2
    assert result.segments[0]["text"] == "안녕하세요"
    assert result.segments[1]["text"] == "반갑습니다"
    assert result.language_detected == "ko"
    assert result.duration == pytest.approx(1.0)


def test_transcribe_audio_returns_quality_flags(tmp_path: Path, monkeypatch) -> None:
    """transcribe_audio returns AsrQualityFlags model."""
    import tube_scout.services.asr as asr_module
    monkeypatch.setattr(asr_module, "_load_model", lambda *a, **k: _FakeWhisperModel())

    wav_path = tmp_path / "test_silent.wav"
    _write_silent_wav(wav_path)

    from tube_scout.models.content import AsrQualityFlags
    from tube_scout.services.asr import transcribe_audio

    result = transcribe_audio(wav_path, model_size="large-v3", compute_type="int8_float16", device="cpu", device_index=0)

    assert isinstance(result.asr_quality_flags, AsrQualityFlags)


def test_transcribe_audio_caption_source_detail_format(tmp_path: Path, monkeypatch) -> None:
    """caption_source_detail has format 'asr:faster-whisper:<size>:<compute_type>'."""
    import tube_scout.services.asr as asr_module
    monkeypatch.setattr(asr_module, "_load_model", lambda *a, **k: _FakeWhisperModel())

    wav_path = tmp_path / "test_silent.wav"
    _write_silent_wav(wav_path)

    from tube_scout.services.asr import transcribe_audio

    result = transcribe_audio(wav_path, model_size="medium", compute_type="int8", device="cpu", device_index=0)

    assert result.caption_source_detail == "asr:faster-whisper:medium:int8"


def test_transcribe_audio_hallucination_filler_detected(tmp_path: Path, monkeypatch) -> None:
    """Quality flag silence_hallucination is set when segment contains filler."""
    import tube_scout.services.asr as asr_module

    class _FillerModel:
        def __init__(self, *a, **k):
            pass

        def transcribe(self, path, **kw):
            segments = [
                _FakeSegment(0.0, 1.0, "구독과 좋아요 부탁드립니다"),
            ]
            info = type("Info", (), {"language": "ko", "duration": 1.0})()
            return iter(segments), info

    monkeypatch.setattr(asr_module, "_load_model", lambda *a, **k: _FillerModel())

    wav_path = tmp_path / "test_filler.wav"
    _write_silent_wav(wav_path)

    from tube_scout.services.asr import transcribe_audio

    result = transcribe_audio(wav_path, model_size="large-v3", compute_type="int8_float16", device="cpu", device_index=0)

    assert result.asr_quality_flags.silence_hallucination is True


def test_transcribe_audio_real_model_env_gated(tmp_path: Path) -> None:
    """Real model transcription — skipped unless TUBE_SCOUT_POC_VIDEO_PATH is set."""
    import os

    poc_path = os.environ.get("TUBE_SCOUT_POC_VIDEO_PATH")
    if not poc_path:
        pytest.skip("TUBE_SCOUT_POC_VIDEO_PATH not set — skipping real model test")

    from tube_scout.services.asr import transcribe_audio

    wav_path = Path(poc_path)
    assert wav_path.exists(), f"TUBE_SCOUT_POC_VIDEO_PATH does not exist: {wav_path}"

    result = transcribe_audio(wav_path, model_size="large-v3", compute_type="int8_float16", device="cuda", device_index=0)
    assert len(result.segments) > 0
    assert result.language_detected in ("ko", "en", "ja", "zh")
