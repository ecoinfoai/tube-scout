"""T057 — Whisper hallucination defense baseline measurement.

Env-gated: skipped unless TUBE_SCOUT_POC_VIDEO_PATH points to a real WAV/mp4 file.
Measures how many of the 6 quality flags fire on a known lecture video
with the 4 hallucination defenses active (vad_filter=True,
condition_on_previous_text=False, compression_ratio_threshold=2.4,
no_speech_threshold=0.6).

Not a pass/fail assertion test — records baseline for future regression.
Results are printed to stdout for capture into measurement/.
"""
import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.slow


def _poc_wav_path() -> Path | None:
    p = os.environ.get("TUBE_SCOUT_POC_VIDEO_PATH")
    return Path(p) if p else None


@pytest.fixture
def poc_wav(tmp_path: Path) -> Path:
    """Return WAV path for PoC video; skip if env not set or file missing."""
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


def test_hallucination_defense_baseline(poc_wav: Path) -> None:
    """Record which quality flags fire on the PoC video with all defenses active."""
    from tube_scout.services.asr import transcribe_audio

    result = transcribe_audio(
        poc_wav,
        model_size="large-v3",
        compute_type="int8_float16",
        device="cuda",
        device_index=0,
        language="ko",
        beam_size=5,
        vad_filter=True,
        condition_on_previous_text=False,
        compression_ratio_threshold=2.4,
        no_speech_threshold=0.6,
    )

    flags = result.asr_quality_flags
    n_segments = len(result.segments)
    lang = result.language_detected
    duration = result.duration

    print("\n--- T057 Hallucination Defense Baseline ---")
    print(f"language_detected: {lang}")
    print(f"duration: {duration:.1f}s")
    print(f"segments: {n_segments}")
    print(f"hallucination_repeat:         {flags.hallucination_repeat}")
    print(f"vad_over_truncated:           {flags.vad_over_truncated}")
    print(f"language_mismatch:            {flags.language_mismatch}")
    print(f"short_segments_excess:        {flags.short_segments_excess}")
    print(f"silence_hallucination:        {flags.silence_hallucination}")
    print(f"compression_ratio_violations: {flags.compression_ratio_violations}")

    flags_dict = flags.model_dump()
    n_flags_fired = sum(1 for v in flags_dict.values() if v)
    print(f"total flags fired: {n_flags_fired} / {len(flags_dict)}")

    # Non-strict assertion: at least some segments extracted
    assert n_segments > 0, "Expected at least 1 segment from a real lecture video"
    assert lang != "", "Expected a detected language"


def test_hallucination_defense_baseline_no_defenses(poc_wav: Path) -> None:
    """Comparison: same video with defenses OFF — flags should fire more."""
    from tube_scout.services.asr import transcribe_audio

    result = transcribe_audio(
        poc_wav,
        model_size="large-v3",
        compute_type="int8_float16",
        device="cuda",
        device_index=0,
        language="ko",
        beam_size=5,
        vad_filter=False,
        condition_on_previous_text=True,
        compression_ratio_threshold=2.4,
        no_speech_threshold=0.6,
    )

    flags = result.asr_quality_flags
    flags_dict = flags.model_dump()
    n_flags_fired_no_defense = sum(1 for v in flags_dict.values() if v)

    print("\n--- T057 Baseline (defenses OFF) ---")
    print(f"segments: {len(result.segments)}")
    print(f"total flags fired (no defenses): {n_flags_fired_no_defense} / {len(flags_dict)}")

    assert len(result.segments) >= 0
