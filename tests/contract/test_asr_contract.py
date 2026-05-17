"""Contract tests — asr service signatures (spec 013 T042 RED).

FR-016~FR-023: transcribe_audio signature, PRESET_TABLE, caption_source_detail format.
Module does not exist yet — all tests should fail at import.
"""

from __future__ import annotations

import inspect
import re

import pytest


# ---------------------------------------------------------------------------
# T042-1: transcribe_audio signature matches contract
# ---------------------------------------------------------------------------

def test_transcribe_audio_signature_matches_contract() -> None:
    """transcribe_audio must have the exact parameter set from the contract."""
    from tube_scout.services.asr import transcribe_audio

    sig = inspect.signature(transcribe_audio)
    params = sig.parameters

    required_params = [
        "wav_path",
        "model_size",
        "compute_type",
        "device",
        "device_index",
        "language",
        "beam_size",
        "vad_filter",
        "condition_on_previous_text",
        "compression_ratio_threshold",
        "no_speech_threshold",
        "model_cache_dir",
    ]

    for name in required_params:
        assert name in params, f"Parameter '{name}' missing from transcribe_audio signature"

    # Verify keyword-only defaults
    assert params["model_size"].default == "large-v3"
    assert params["compute_type"].default == "int8_float16"
    assert params["device"].default == "cuda"
    assert params["device_index"].default == 0
    assert params["language"].default == "ko"
    assert params["beam_size"].default == 5
    assert params["vad_filter"].default is True
    assert params["condition_on_previous_text"].default is False
    assert params["compression_ratio_threshold"].default == 2.4
    assert params["no_speech_threshold"].default == 0.6
    assert params["model_cache_dir"].default is None


# ---------------------------------------------------------------------------
# T042-2: PRESET_TABLE has 4 presets x 4 required keys
# ---------------------------------------------------------------------------

def test_preset_table_has_required_keys() -> None:
    """PRESET_TABLE must have the 4 canonical presets, each with the four
    required kwargs. spec 013 originally shipped role-tagged names
    (poc-laptop / prod-a6000 / prod-a6000-pool / cpu-fallback); those are
    preserved as :data:`PRESET_ALIASES` for backward compat. The canonical
    keys are now function-based (gpu-quantized / gpu-native / gpu-pool / cpu)
    so operators do not have to pretend their host is a specific lab machine.
    """
    from tube_scout.services.asr import PRESET_ALIASES, PRESET_TABLE

    required_presets = {"gpu-quantized", "gpu-native", "gpu-pool", "cpu"}
    required_keys = {"model", "compute_type", "device", "device_index"}

    assert set(PRESET_TABLE.keys()) == required_presets, (
        f"PRESET_TABLE must have exactly {required_presets}, "
        f"got {set(PRESET_TABLE.keys())}"
    )

    for preset_name, preset in PRESET_TABLE.items():
        missing = required_keys - set(preset.keys())
        assert not missing, (
            f"Preset '{preset_name}' missing keys: {missing}"
        )

    # Spot-check canonical values
    assert PRESET_TABLE["gpu-quantized"]["model"] == "large-v3"
    assert PRESET_TABLE["gpu-quantized"]["compute_type"] == "int8_float16"
    assert PRESET_TABLE["gpu-native"]["compute_type"] == "float16"
    assert PRESET_TABLE["gpu-pool"]["device_index"] is None
    assert PRESET_TABLE["cpu"]["model"] == "medium"
    assert PRESET_TABLE["cpu"]["compute_type"] == "int8"
    assert PRESET_TABLE["cpu"]["device"] == "cpu"

    # The legacy role-tagged names must still resolve through aliases so
    # operator scripts that hard-code them keep working.
    assert PRESET_ALIASES == {
        "poc-laptop":      "gpu-quantized",
        "prod-a6000":      "gpu-native",
        "prod-a6000-pool": "gpu-pool",
        "cpu-fallback":    "cpu",
    }


# ---------------------------------------------------------------------------
# T042-3: caption_source_detail format regex
# ---------------------------------------------------------------------------

def test_caption_source_detail_format() -> None:
    """caption_source_detail must match 'asr:faster-whisper:<size>:<compute_type>'."""
    from tube_scout.services.asr import PRESET_TABLE

    pattern = re.compile(r"^asr:faster-whisper:\S+:\S+$")

    # Build expected caption_source_detail strings from PRESET_TABLE
    for preset_name, preset in PRESET_TABLE.items():
        source_detail = f"asr:faster-whisper:{preset['model']}:{preset['compute_type']}"
        assert pattern.match(source_detail), (
            f"caption_source_detail '{source_detail}' for preset '{preset_name}' "
            f"does not match pattern {pattern.pattern}"
        )
