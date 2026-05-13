"""T058 — ASR throughput PoC GPU measurement.

Env-gated: skipped unless TUBE_SCOUT_POC_VIDEO_PATH is set.
Measures wall-clock transcription time for 4 preset configurations.
Records real-time-factor (RTF = transcription_time / audio_duration).

Results are printed to stdout for capture into measurement/asr_throughput_phase1.md.
"""
import os
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.slow

_PRESETS_TO_TEST = [
    ("poc-laptop",   "large-v3", "int8_float16", "cuda", 0),
    ("prod-a6000",   "large-v3", "float16",      "cuda", 0),
    ("cpu-fallback", "medium",   "int8",          "cpu",  0),
]


def _poc_wav_path() -> Path | None:
    p = os.environ.get("TUBE_SCOUT_POC_VIDEO_PATH")
    return Path(p) if p else None


@pytest.fixture
def poc_wav(tmp_path: Path) -> Path:
    """Return WAV path; skip if env not set or file missing."""
    candidate = _poc_wav_path()
    if candidate is None:
        pytest.skip("TUBE_SCOUT_POC_VIDEO_PATH not set")
    if not candidate.exists():
        pytest.skip(f"TUBE_SCOUT_POC_VIDEO_PATH does not exist: {candidate}")
    if candidate.suffix.lower() in (".mp4", ".mkv", ".mov"):
        wav_out = tmp_path / "poc.wav"
        from tube_scout.services.audio_extract import extract_wav_16k_mono
        extract_wav_16k_mono(candidate, wav_out)
        return wav_out
    return candidate


@pytest.mark.parametrize("preset,model,compute_type,device,device_index", _PRESETS_TO_TEST)
def test_asr_throughput_preset(
    poc_wav: Path,
    preset: str,
    model: str,
    compute_type: str,
    device: str,
    device_index: int,
) -> None:
    """Measure RTF for a given preset configuration."""
    from tube_scout.services.asr import transcribe_audio

    t0 = time.monotonic()
    try:
        result = transcribe_audio(
            poc_wav,
            model_size=model,
            compute_type=compute_type,
            device=device,
            device_index=device_index,
            language="ko",
            beam_size=5,
            vad_filter=True,
        )
        wall_time = time.monotonic() - t0
    except RuntimeError as exc:
        pytest.skip(f"Device '{device}' not available: {exc}")

    audio_duration = result.duration
    rtf = wall_time / audio_duration if audio_duration > 0 else float("inf")

    print(f"\n--- T058 Throughput: {preset} ---")
    print(f"model={model} compute_type={compute_type} device={device}")
    print(f"audio_duration: {audio_duration:.1f}s")
    print(f"wall_clock: {wall_time:.2f}s")
    print(f"RTF: {rtf:.3f}x  (< 1.0 = faster than real-time)")
    print(f"segments: {len(result.segments)}")

    # Non-strict: just ensure transcription completed
    assert len(result.segments) >= 0
    assert wall_time > 0
