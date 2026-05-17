"""Unit tests for ASR preset resolution + auto-detect decision flow.

Verifies the layered ``resolve_preset`` ordering:

  1. explicit ``--preset`` argument wins,
  2. ``TUBE_SCOUT_ASR_PRESET`` env variable wins over auto-detect,
  3. auto-detect splits across four branches:
     * no CUDA GPU / GPU < 4 GiB → ``cpu``
     * 4 GiB ≤ GPU < 16 GiB → ``gpu-quantized``
     * GPU ≥ 16 GiB, single card → ``gpu-native``
     * GPU ≥ 16 GiB, multiple cards → ``gpu-pool``

Also verifies backward-compat aliases for the prior poc-laptop / prod-a6000 /
prod-a6000-pool / cpu-fallback names.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from tube_scout.services.asr import (
    ENV_ASR_PRESET,
    PRESET_ALIASES,
    PRESET_TABLE,
    preset_kwargs,
    resolve_preset,
)


class TestExplicitPreset:
    """Layer 1 — explicit CLI flag wins."""

    def test_explicit_cpu(self) -> None:
        result = resolve_preset("cpu", env={ENV_ASR_PRESET: "gpu-native"})
        assert result.preset_name == "cpu"
        assert result.source == "explicit"

    def test_explicit_overrides_env(self) -> None:
        """Explicit beats env (deterministic CLI run)."""
        result = resolve_preset("gpu-native", env={ENV_ASR_PRESET: "cpu"})
        assert result.preset_name == "gpu-native"
        assert result.source == "explicit"

    def test_unknown_explicit_preset_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown ASR preset"):
            resolve_preset("bogus-preset", env={})


class TestEnvPreset:
    """Layer 2 — env variable wins when explicit is absent."""

    def test_env_preset_used(self) -> None:
        result = resolve_preset(None, env={ENV_ASR_PRESET: "gpu-pool"})
        assert result.preset_name == "gpu-pool"
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
    """Layer 3 — four-way VRAM + GPU-count classification."""

    def test_no_gpu_picks_cpu(self) -> None:
        with patch(
            "tube_scout.services.asr._detect_gpu_vram_gib", return_value=None
        ):
            result = resolve_preset(None, env={})
        assert result.preset_name == "cpu"
        assert result.source == "auto"
        assert "no CUDA GPU" in result.rationale

    def test_below_quantized_threshold_picks_cpu(self) -> None:
        """A < 4 GiB card cannot fit even quantized large-v3."""
        with patch(
            "tube_scout.services.asr._detect_gpu_vram_gib", return_value=2.0
        ):
            result = resolve_preset(None, env={})
        assert result.preset_name == "cpu"
        assert result.source == "auto"
        assert "2.0 GiB" in result.rationale

    def test_midrange_gpu_picks_quantized(self) -> None:
        """4-16 GiB GPUs (RTX 3060 6 GB, RTX 4070 12 GB) get the quantized
        preset so large-v3 + int8_float16 fits VRAM safely."""
        with patch(
            "tube_scout.services.asr._detect_gpu_vram_gib", return_value=6.0
        ):
            with patch(
                "tube_scout.services.asr._detect_gpu_count", return_value=1
            ):
                result = resolve_preset(None, env={})
        assert result.preset_name == "gpu-quantized"
        assert result.source == "auto"
        assert "6.0 GiB" in result.rationale

    def test_large_single_gpu_picks_native(self) -> None:
        """Single >= 16 GiB GPU (RTX 3090 24 GB, A6000 48 GB) gets the
        native float16 preset."""
        with patch(
            "tube_scout.services.asr._detect_gpu_vram_gib", return_value=24.0
        ):
            with patch(
                "tube_scout.services.asr._detect_gpu_count", return_value=1
            ):
                result = resolve_preset(None, env={})
        assert result.preset_name == "gpu-native"
        assert result.source == "auto"
        assert "single GPU" in result.rationale

    def test_multi_large_gpu_picks_pool(self) -> None:
        """Two or more >= 16 GiB GPUs (e.g. A6000 × 2) get the multi-GPU
        pool preset."""
        with patch(
            "tube_scout.services.asr._detect_gpu_vram_gib", return_value=48.0
        ):
            with patch(
                "tube_scout.services.asr._detect_gpu_count", return_value=2
            ):
                result = resolve_preset(None, env={})
        assert result.preset_name == "gpu-pool"
        assert result.source == "auto"
        assert "2 GPUs" in result.rationale

    def test_multi_small_gpu_stays_quantized(self) -> None:
        """Multiple small GPUs (6 GiB × 2) still pick quantized — pool is
        reserved for the workstation-class native float16 path."""
        with patch(
            "tube_scout.services.asr._detect_gpu_vram_gib", return_value=6.0
        ):
            with patch(
                "tube_scout.services.asr._detect_gpu_count", return_value=2
            ):
                result = resolve_preset(None, env={})
        assert result.preset_name == "gpu-quantized"


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

    def test_cpu_targets_cpu(self) -> None:
        kw = preset_kwargs("cpu")
        assert kw["device"] == "cpu"
        assert kw["model_size"] == "medium"

    def test_gpu_quantized_uses_int8_float16(self) -> None:
        kw = preset_kwargs("gpu-quantized")
        assert kw["device"] == "cuda"
        assert kw["model_size"] == "large-v3"
        assert kw["compute_type"] == "int8_float16"

    def test_gpu_native_uses_float16(self) -> None:
        kw = preset_kwargs("gpu-native")
        assert kw["device"] == "cuda"
        assert kw["compute_type"] == "float16"

    def test_gpu_pool_uses_float16_with_pool_device_index(self) -> None:
        """gpu-pool's device_index is None in PRESET_TABLE so CTranslate2
        distributes across all visible CUDA devices. preset_kwargs converts
        None → 0 for the kw dict — actual pool dispatch happens lower."""
        raw = PRESET_TABLE["gpu-pool"]
        assert raw["device_index"] is None
        kw = preset_kwargs("gpu-pool")
        assert kw["compute_type"] == "float16"


class TestBackwardCompatAliases:
    """Deprecated machine/role-tagged names map to canonical preset keys."""

    @pytest.mark.parametrize(
        "alias,canonical",
        list(PRESET_ALIASES.items()),
    )
    def test_alias_resolves_to_canonical(self, alias: str, canonical: str) -> None:
        """All legacy aliases are accepted as --preset values."""
        result = resolve_preset(alias, env={})
        assert result.preset_name == canonical
        assert result.source == "explicit"
        assert canonical in result.rationale

    @pytest.mark.parametrize(
        "alias,canonical",
        list(PRESET_ALIASES.items()),
    )
    def test_alias_via_env_resolves(self, alias: str, canonical: str) -> None:
        """Legacy env values are also accepted."""
        result = resolve_preset(None, env={ENV_ASR_PRESET: alias})
        assert result.preset_name == canonical
        assert result.source == "env"

    @pytest.mark.parametrize(
        "alias,canonical",
        list(PRESET_ALIASES.items()),
    )
    def test_alias_in_preset_kwargs(self, alias: str, canonical: str) -> None:
        """preset_kwargs also accepts legacy aliases."""
        kw_alias = preset_kwargs(alias)
        kw_canon = preset_kwargs(canonical)
        assert kw_alias == kw_canon
