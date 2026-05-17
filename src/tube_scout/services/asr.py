"""ASR service — faster-whisper wrapper with hallucination defenses (spec 013 FR-016~FR-023)."""

from __future__ import annotations

import functools
import logging
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel

from tube_scout.models.content import AsrQualityFlags

if TYPE_CHECKING:
    from faster_whisper import WhisperModel

_logger = logging.getLogger(__name__)

# Substrings observed in ``ctranslate2`` / ``faster-whisper`` errors when a
# CUDA runtime library failed to dlopen at first model load. Used by
# :func:`transcribe_audio` to classify the outer ``except Exception`` so
# operators see an actionable, environment-shaped message instead of an
# opaque transcription error. cuRAND is intentionally absent: binary
# analysis on nixpkgs 8110df5 / CUDA 12.9 confirmed CTranslate2 4.7.x does
# NOT dlopen libcurand (audit v3 G-4, 2026-05-17). Adding it here would
# misclassify unrelated CUDA errors as a missing-library problem.
_CUDA_RUNTIME_ERROR_MARKERS: tuple[str, ...] = (
    "libcublas",
    "libcublasLt",
    "libcudart",
    "is not found or cannot be loaded",
    "ctranslate2",
)

ModelSize = Literal["tiny", "base", "small", "medium", "large-v3"]
ComputeType = Literal["float32", "float16", "int8_float16", "int8"]
Device = Literal["cuda", "cpu"]

PRESET_TABLE: dict[str, dict[str, str | int | None]] = {
    "gpu-quantized": {"model": "large-v3", "compute_type": "int8_float16", "device": "cuda", "device_index": 0},
    "gpu-native":    {"model": "large-v3", "compute_type": "float16",      "device": "cuda", "device_index": 0},
    "gpu-pool":      {"model": "large-v3", "compute_type": "float16",      "device": "cuda", "device_index": None},
    "cpu":           {"model": "medium",   "compute_type": "int8",         "device": "cpu",  "device_index": 0},
}

# Backward-compat aliases for preset names. Released as 0.6.0 with the old
# machine/role-tagged keys; rename here keeps existing CLI invocations and
# `TUBE_SCOUT_ASR_PRESET` env values working transparently until a deprecation
# window expires.
PRESET_ALIASES: dict[str, str] = {
    "poc-laptop":      "gpu-quantized",
    "prod-a6000":      "gpu-native",
    "prod-a6000-pool": "gpu-pool",
    "cpu-fallback":    "cpu",
}

# Environment variable that overrides preset auto-detection when --preset is
# not passed on the command line. Operator-level shell rc setting.
ENV_ASR_PRESET = "TUBE_SCOUT_ASR_PRESET"

# GPU VRAM threshold (GiB) above which large-v3 fits a single card with the
# native float16 compute_type. Below this we still use a GPU but with the
# int8_float16 quantized preset to stay inside VRAM budgets. Below the lower
# threshold we drop to CPU.
_GPU_VRAM_NATIVE_THRESHOLD_GIB: float = 16.0
_GPU_VRAM_QUANTIZED_THRESHOLD_GIB: float = 4.0


def _canonical_preset(name: str) -> str:
    """Return the canonical preset name, translating any deprecated alias.

    Args:
        name: Preset name as supplied by CLI flag, env variable, or caller.

    Returns:
        Canonical name (key of :data:`PRESET_TABLE`) if input matched a
        current key or a known alias; otherwise the input unchanged so that
        downstream validation can raise with the original spelling.
    """
    if name in PRESET_TABLE:
        return name
    return PRESET_ALIASES.get(name, name)


def _detect_gpu_count() -> int:
    """Return the visible CUDA GPU count, or 0 if no CUDA runtime is available.

    Used to upgrade :func:`resolve_preset` to ``gpu-pool`` when more than one
    workstation-class GPU is present.

    Returns:
        Number of GPUs visible to torch.cuda or nvidia-smi; 0 when neither
        path reports a GPU.
    """
    try:
        import torch
        if torch.cuda.is_available():
            return int(torch.cuda.device_count())
    except Exception as exc:
        _logger.debug("GPU count via torch.cuda failed: %s", exc)

    if shutil.which("nvidia-smi") is None:
        _logger.debug("GPU count via nvidia-smi skipped: binary not on PATH")
        return 0
    try:
        import subprocess
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=count", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if out.returncode == 0 and out.stdout.strip():
            # nvidia-smi returns one line per GPU; count returns each GPU's
            # idx field which equals the total count when summed across rows.
            return len(out.stdout.strip().splitlines())
    except Exception as exc:
        _logger.debug("GPU count via nvidia-smi failed: %s", exc)

    return 0


@dataclass(frozen=True)
class PresetResolution:
    """Outcome of :func:`resolve_preset`.

    Attributes:
        preset_name: One of :data:`PRESET_TABLE` keys.
        source: Where the choice came from — ``"explicit"`` (CLI flag),
            ``"env"`` (``TUBE_SCOUT_ASR_PRESET``), or ``"auto"`` (GPU VRAM
            sniff). Used for stdout transparency so operators see why the
            preset was chosen.
        rationale: Short human-readable explanation rendered to stdout.
    """

    preset_name: str
    source: Literal["explicit", "env", "auto"]
    rationale: str


def _detect_gpu_vram_gib() -> float | None:
    """Return total VRAM (GiB) of GPU 0, or ``None`` if no CUDA GPU is usable.

    Tries ``torch.cuda`` first (commonly already installed for ml-sentiment
    extra); falls back to parsing ``nvidia-smi --query-gpu=memory.total``
    when torch is absent so cpu-only hosts still report ``None`` quickly.

    Returns:
        VRAM size in GiB, or ``None`` when GPU 0 is not visible.
    """
    try:
        import torch
        if torch.cuda.is_available() and torch.cuda.device_count() > 0:
            props = torch.cuda.get_device_properties(0)
            return float(props.total_memory) / (1024 ** 3)
    except Exception as exc:
        _logger.debug("VRAM via torch.cuda failed: %s", exc)

    if shutil.which("nvidia-smi") is None:
        _logger.debug("VRAM via nvidia-smi skipped: binary not on PATH")
        return None
    try:
        import subprocess
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if out.returncode == 0 and out.stdout.strip():
            mib = float(out.stdout.strip().splitlines()[0])
            return mib / 1024.0
    except Exception as exc:
        _logger.debug("VRAM via nvidia-smi failed: %s", exc)

    return None


def resolve_preset(
    explicit_preset: str | None = None,
    *,
    env: dict[str, str] | None = None,
) -> PresetResolution:
    """Resolve which ASR preset to use given the 3-layer decision flow.

    Layers, in priority order:
      1. ``explicit_preset`` (e.g. ``collect ingest --preset cpu-fallback``).
      2. ``TUBE_SCOUT_ASR_PRESET`` environment variable.
      3. Auto-detect — measure GPU VRAM via :func:`_detect_gpu_vram_gib`;
         choose ``poc-laptop`` when ``>= 8 GiB``, otherwise ``cpu-fallback``.

    Args:
        explicit_preset: CLI-supplied preset name or ``None``.
        env: Optional override for the environment dict (defaults to
            ``os.environ``). Mostly used by tests.

    Returns:
        A :class:`PresetResolution` describing the chosen preset, the source
        of the choice, and a one-line rationale for stdout.

    Raises:
        ValueError: ``explicit_preset`` or the env value is not a known
            preset name. The error message lists valid names.
    """
    env_map = env if env is not None else os.environ

    if explicit_preset:
        canon = _canonical_preset(explicit_preset)
        if canon not in PRESET_TABLE:
            raise ValueError(
                f"Unknown ASR preset {explicit_preset!r}. "
                f"Valid: {sorted(PRESET_TABLE.keys())}."
            )
        return PresetResolution(
            preset_name=canon,
            source="explicit",
            rationale=(
                f"--preset {canon}" if canon == explicit_preset
                else f"--preset {explicit_preset} → {canon}"
            ),
        )

    env_value = env_map.get(ENV_ASR_PRESET)
    if env_value:
        canon = _canonical_preset(env_value)
        if canon not in PRESET_TABLE:
            raise ValueError(
                f"Environment {ENV_ASR_PRESET}={env_value!r} is not a known "
                f"preset. Valid: {sorted(PRESET_TABLE.keys())}."
            )
        return PresetResolution(
            preset_name=canon,
            source="env",
            rationale=(
                f"{ENV_ASR_PRESET}={canon}" if canon == env_value
                else f"{ENV_ASR_PRESET}={env_value} → {canon}"
            ),
        )

    vram = _detect_gpu_vram_gib()
    if vram is None:
        return PresetResolution(
            preset_name="cpu",
            source="auto",
            rationale="no CUDA GPU detected",
        )
    if vram < _GPU_VRAM_QUANTIZED_THRESHOLD_GIB:
        return PresetResolution(
            preset_name="cpu",
            source="auto",
            rationale=(
                f"GPU has {vram:.1f} GiB (< {_GPU_VRAM_QUANTIZED_THRESHOLD_GIB} GiB) — "
                "even quantized large-v3 would OOM"
            ),
        )
    if vram < _GPU_VRAM_NATIVE_THRESHOLD_GIB:
        return PresetResolution(
            preset_name="gpu-quantized",
            source="auto",
            rationale=(
                f"GPU has {vram:.1f} GiB "
                f"(>= {_GPU_VRAM_QUANTIZED_THRESHOLD_GIB} GiB, "
                f"< {_GPU_VRAM_NATIVE_THRESHOLD_GIB} GiB) — "
                "int8_float16 fits, float16 would not"
            ),
        )
    gpu_count = _detect_gpu_count()
    if gpu_count > 1:
        return PresetResolution(
            preset_name="gpu-pool",
            source="auto",
            rationale=(
                f"{gpu_count} GPUs detected, GPU 0 has {vram:.1f} GiB "
                f"(>= {_GPU_VRAM_NATIVE_THRESHOLD_GIB} GiB) — "
                "native float16 with multi-GPU pool"
            ),
        )
    return PresetResolution(
        preset_name="gpu-native",
        source="auto",
        rationale=(
            f"GPU has {vram:.1f} GiB "
            f"(>= {_GPU_VRAM_NATIVE_THRESHOLD_GIB} GiB) — "
            "native float16 on single GPU"
        ),
    )


def preset_kwargs(preset_name: str) -> dict[str, str | int]:
    """Return ``transcribe_audio`` kwargs for a preset name.

    Accepts either a current canonical name from :data:`PRESET_TABLE` or a
    deprecated alias from :data:`PRESET_ALIASES`.

    Args:
        preset_name: One of :data:`PRESET_TABLE` keys (or an alias).

    Returns:
        Dict ready to splat into :func:`transcribe_audio` — keys
        ``model_size``, ``compute_type``, ``device``, ``device_index``.

    Raises:
        KeyError: ``preset_name`` not in :data:`PRESET_TABLE` or aliases.
    """
    canon = _canonical_preset(preset_name)
    if canon not in PRESET_TABLE:
        raise KeyError(
            f"Unknown preset {preset_name!r}. Valid: {sorted(PRESET_TABLE.keys())}."
        )
    p = PRESET_TABLE[canon]
    device_index = p["device_index"]
    return {
        "model_size": str(p["model"]),
        "compute_type": str(p["compute_type"]),
        "device": str(p["device"]),
        "device_index": int(device_index) if device_index is not None else 0,
    }

_SILENCE_FILLER_PATTERNS: list[re.Pattern[str]] = [
    re.compile(p, re.IGNORECASE) for p in [
        r"구독과\s*좋아요",
        r"시청해\s*주셔서\s*감사합니다",
        r"구독\s*부탁드립니다",
        r"좋아요와\s*구독",
        r"알림\s*설정",
        r"구독\s*좋아요\s*알림",
        r"like\s*and\s*subscribe",
    ]
]


class Segment(BaseModel):
    """Single transcript segment."""

    start: float
    end: float
    text: str
    compression_ratio: float = 0.0
    no_speech_prob: float = 0.0


class TranscribeResult(BaseModel):
    """Result of ASR transcription."""

    segments: list[dict]
    language_detected: str
    duration: float
    asr_quality_flags: AsrQualityFlags
    caption_source_detail: str


@functools.lru_cache(maxsize=1)
def _load_model(
    model_size: str,
    compute_type: str,
    device: str,
    device_index: int | None,
    model_cache_dir: Path | None,
) -> WhisperModel:
    """Load WhisperModel singleton per (model_size, compute_type, device, device_index)."""
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise ImportError(
            "faster-whisper is not installed. "
            "Install with: uv sync --extra asr\n"
            "or: pip install 'tube-scout[asr]'"
        ) from exc

    return WhisperModel(
        model_size,
        device=device,
        device_index=device_index if device_index is not None else 0,
        compute_type=compute_type,
        download_root=str(model_cache_dir) if model_cache_dir else None,
    )


def _detect_repeat_n(segments: list[dict], n: int = 3) -> bool:
    """Return True when n+ consecutive segments have identical normalized text.

    Args:
        segments: List of segment dicts with 'text' key.
        n: Consecutive repeat threshold.

    Returns:
        True if any n consecutive segments are textually identical.
    """
    if len(segments) < n:
        return False
    texts = [s.get("text", "").strip() for s in segments]
    count = 1
    for i in range(1, len(texts)):
        if texts[i] == texts[i - 1] and texts[i]:
            count += 1
            if count >= n:
                return True
        else:
            count = 1
    return False


def _detect_silence_filler(segments: list[dict]) -> bool:
    """Return True when any segment contains a known silence hallucination pattern.

    Args:
        segments: List of segment dicts with 'text' key.

    Returns:
        True if any silence filler pattern is detected.
    """
    for seg in segments:
        text = seg.get("text", "")
        for pattern in _SILENCE_FILLER_PATTERNS:
            if pattern.search(text):
                return True
    return False


def _ratio_short_segments(
    segments: list[dict],
    threshold: float = 0.5,
    ratio: float = 0.30,
) -> bool:
    """Return True when >ratio fraction of segments are shorter than threshold seconds.

    Args:
        segments: List of segment dicts with 'start'/'end' keys.
        threshold: Duration in seconds below which a segment is considered short.
        ratio: Fraction threshold above which flag triggers.

    Returns:
        True if short_ratio > ratio.
    """
    if not segments:
        return False
    short = sum(
        1 for s in segments
        if (s.get("end", 0.0) - s.get("start", 0.0)) < threshold
    )
    return (short / len(segments)) > ratio


def _count_compression_violations(
    segments: list[dict],
    threshold: float = 2.4,
) -> int:
    """Count segments whose compression_ratio exceeds threshold.

    Args:
        segments: List of segment dicts, optionally with 'compression_ratio' key.
        threshold: Compression ratio above which a violation is counted.

    Returns:
        Number of violating segments.
    """
    return sum(
        1 for s in segments
        if s.get("compression_ratio", 0.0) > threshold
    )


def detect_quality_flags(
    segments: list[dict],
    language_detected: str,
    expected_lang: str,
    audio_duration: float,
) -> AsrQualityFlags:
    """Detect ASR quality issues post-transcription.

    Args:
        segments: Transcript segments from faster-whisper.
        language_detected: Language code detected by ASR.
        expected_lang: Expected language code (e.g. 'ko').
        audio_duration: Total audio duration in seconds.

    Returns:
        AsrQualityFlags with 6 quality indicators.
    """
    return AsrQualityFlags(
        hallucination_repeat=_detect_repeat_n(segments, n=3),
        vad_over_truncated=False,
        language_mismatch=(language_detected != expected_lang),
        short_segments_excess=_ratio_short_segments(segments, threshold=0.5, ratio=0.30),
        silence_hallucination=_detect_silence_filler(segments),
        compression_ratio_violations=_count_compression_violations(segments),
    )


def transcribe_audio(
    wav_path: Path,
    *,
    model_size: ModelSize = "large-v3",
    compute_type: ComputeType = "int8_float16",
    device: Device = "cuda",
    device_index: int = 0,
    language: str = "ko",
    beam_size: int = 5,
    vad_filter: bool = True,
    condition_on_previous_text: bool = False,
    compression_ratio_threshold: float = 2.4,
    no_speech_threshold: float = 0.6,
    model_cache_dir: Path | None = None,
) -> TranscribeResult:
    """Transcribe a 16 kHz mono WAV via faster-whisper.

    Args:
        wav_path: 16 kHz mono PCM WAV path.
        model_size: Whisper model size.
        compute_type: Quantization type.
        device: 'cuda' or 'cpu'.
        device_index: GPU device index.
        language: Language code for transcription (forced).
        beam_size: Beam search width.
        vad_filter: Enable silero-VAD filtering (FR-017 default True).
        condition_on_previous_text: Condition on prior text (FR-017 default False).
        compression_ratio_threshold: Drop segments above this ratio (FR-017).
        no_speech_threshold: Exclude segments with no_speech_prob above this (FR-017).
        model_cache_dir: Override HF_HOME model cache directory.

    Returns:
        TranscribeResult with segments, language, quality flags, caption_source_detail.

    Raises:
        ImportError: faster-whisper is not installed (actionable message).
        FileNotFoundError: wav_path does not exist.
        RuntimeError: faster-whisper internal error.
    """
    if not wav_path.exists():
        raise FileNotFoundError(f"WAV file not found: {wav_path}")

    try:
        model = _load_model(model_size, compute_type, device, device_index, model_cache_dir)
    except ImportError:
        raise

    try:
        segments_iter, info = model.transcribe(
            str(wav_path),
            language=language,
            beam_size=beam_size,
            vad_filter=vad_filter,
            condition_on_previous_text=condition_on_previous_text,
            compression_ratio_threshold=compression_ratio_threshold,
            no_speech_threshold=no_speech_threshold,
        )

        segments: list[dict] = []
        for seg in segments_iter:
            if getattr(seg, "no_speech_prob", 0.0) > no_speech_threshold:
                continue
            segments.append({
                "start": seg.start,
                "end": seg.end,
                "text": seg.text.strip(),
                "compression_ratio": getattr(seg, "compression_ratio", 0.0),
                "no_speech_prob": getattr(seg, "no_speech_prob", 0.0),
            })

        language_detected = getattr(info, "language", language)
        duration = getattr(info, "duration", 0.0)

        flags = detect_quality_flags(
            segments=segments,
            language_detected=language_detected,
            expected_lang=language,
            audio_duration=duration,
        )

        caption_source_detail = f"asr:faster-whisper:{model_size}:{compute_type}"

        return TranscribeResult(
            segments=segments,
            language_detected=language_detected,
            duration=duration,
            asr_quality_flags=flags,
            caption_source_detail=caption_source_detail,
        )

    except ImportError:
        raise
    except Exception as exc:
        message = str(exc)
        if any(marker in message for marker in _CUDA_RUNTIME_ERROR_MARKERS):
            raise RuntimeError(
                "faster-whisper CUDA runtime error: "
                f"{message}. "
                "Hint: verify GPU devShell has cuBLAS/cudart linked "
                "(echo $LD_LIBRARY_PATH | tr : '\\n' | grep cuda); "
                "see flake.nix devShells.gpu (audit v3 F-1) and "
                "docs/quickstart.md GPU section."
            ) from exc
        raise RuntimeError(f"faster-whisper transcription failed: {exc}") from exc
