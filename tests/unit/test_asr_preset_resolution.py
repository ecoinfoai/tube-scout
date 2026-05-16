"""Unit tests for ASR preset 3-layer decision flow (spec 017 / spec 013 preset).

Verifies the layered ``resolve_preset`` ordering:

  1. explicit ``--preset`` argument wins,
  2. ``TUBE_SCOUT_ASR_PRESET`` env variable wins over auto-detect,
  3. auto-detect picks ``poc-laptop`` for >= 8 GiB GPUs and ``cpu-fallback``
     for smaller GPUs or no GPU at all.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from tube_scout.services.asr import (
    ENV_ASR_PRESET,
    PRESET_TABLE,
    preset_kwargs,
    resolve_preset,
)


class TestExplicitPreset:
    """Layer 1 — explicit CLI flag wins."""

    def test_explicit_cpu_fallback(self) -> None:
        result = resolve_preset("cpu-fallback", env={ENV_ASR_PRESET: "poc-laptop"})
        assert result.preset_name == "cpu-fallback"
        assert result.source == "explicit"

    def test_explicit_overrides_env(self) -> None:
        """Explicit beats env (deterministic CLI run)."""
        result = resolve_preset("prod-a6000", env={ENV_ASR_PRESET: "cpu-fallback"})
        assert result.preset_name == "prod-a6000"
        assert result.source == "explicit"

    def test_unknown_explicit_preset_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown ASR preset"):
            resolve_preset("bogus-preset", env={})


class TestEnvPreset:
    """Layer 2 — env variable wins when explicit is absent."""

    def test_env_preset_used(self) -> None:
        result = resolve_preset(None, env={ENV_ASR_PRESET: "prod-a6000-pool"})
        assert result.preset_name == "prod-a6000-pool"
        assert result.source == "env"

    def test_env_unknown_value_raises(self) -> None:
        with pytest.raises(ValueError, match="not a known preset"):
            resolve_preset(None, env={ENV_ASR_PRESET: "nope"})

    def test_empty_env_value_falls_through_to_auto(self) -> None:
        with patch(
            "tube_scout.services.asr._detect_gpu_vram_gib",
            return_value=None,
        ):
            result = resolve_preset(None, env={ENV_ASR_PRESET: ""})
        assert result.source == "auto"


class TestAutoDetect:
    """Layer 3 — VRAM sniffing."""

    def test_no_gpu_falls_back_to_cpu(self) -> None:
        with patch(
            "tube_scout.services.asr._detect_gpu_vram_gib", return_value=None
        ):
            result = resolve_preset(None, env={})
        assert result.preset_name == "cpu-fallback"
        assert result.source == "auto"
        assert "no CUDA GPU" in result.rationale

    def test_small_gpu_below_threshold_falls_back_to_cpu(self) -> None:
        """A < 4 GiB GPU (e.g. legacy 2 GiB laptop card) cannot fit large-v3."""
        with patch(
            "tube_scout.services.asr._detect_gpu_vram_gib", return_value=2.0
        ):
            result = resolve_preset(None, env={})
        assert result.preset_name == "cpu-fallback"
        assert result.source == "auto"
        assert "2.0 GiB" in result.rationale

    def test_laptop_gpu_at_threshold_picks_poc_laptop(self) -> None:
        """RTX 3060 6 GB / RTX 4060 8 GB sit above the 4 GiB safe threshold."""
        with patch(
            "tube_scout.services.asr._detect_gpu_vram_gib", return_value=6.0
        ):
            result = resolve_preset(None, env={})
        assert result.preset_name == "poc-laptop"
        assert result.source == "auto"
        assert "6.0 GiB" in result.rationale

    def test_large_gpu_picks_poc_laptop(self) -> None:
        with patch(
            "tube_scout.services.asr._detect_gpu_vram_gib", return_value=24.0
        ):
            result = resolve_preset(None, env={})
        assert result.preset_name == "poc-laptop"
        assert result.source == "auto"
        assert "24.0 GiB" in result.rationale


class TestPresetKwargs:
    """preset_kwargs maps name → transcribe_audio kwargs."""

    @pytest.mark.parametrize("preset_name", list(PRESET_TABLE.keys()))
    def test_all_presets_produce_complete_kwargs(self, preset_name: str) -> None:
        kw = preset_kwargs(preset_name)
        assert set(kw.keys()) == {"model_size", "compute_type", "device", "device_index"}
        assert kw["device"] in {"cuda", "cpu"}
        assert isinstance(kw["device_index"], int)

    def test_unknown_preset_raises_keyerror(self) -> None:
        with pytest.raises(KeyError, match="Unknown preset"):
            preset_kwargs("missing-preset")

    def test_cpu_fallback_targets_cpu(self) -> None:
        kw = preset_kwargs("cpu-fallback")
        assert kw["device"] == "cpu"
        assert kw["model_size"] == "medium"

    def test_poc_laptop_targets_cuda(self) -> None:
        kw = preset_kwargs("poc-laptop")
        assert kw["device"] == "cuda"
        assert kw["model_size"] == "large-v3"
