"""ASR service — faster-whisper wrapper with hallucination defenses (spec 013 FR-016~FR-023)."""

from __future__ import annotations

import functools
import re
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel

from tube_scout.models.content import AsrQualityFlags

if TYPE_CHECKING:
    pass

ModelSize = Literal["tiny", "base", "small", "medium", "large-v3"]
ComputeType = Literal["float32", "float16", "int8_float16", "int8"]
Device = Literal["cuda", "cpu"]

PRESET_TABLE: dict[str, dict[str, str | int | None]] = {
    "poc-laptop":      {"model": "large-v3", "compute_type": "int8_float16", "device": "cuda", "device_index": 0},
    "prod-a6000":      {"model": "large-v3", "compute_type": "float16",      "device": "cuda", "device_index": 0},
    "prod-a6000-pool": {"model": "large-v3", "compute_type": "float16",      "device": "cuda", "device_index": None},
    "cpu-fallback":    {"model": "medium",   "compute_type": "int8",         "device": "cpu",  "device_index": 0},
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
) -> "object":
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
        raise RuntimeError(f"faster-whisper transcription failed: {exc}") from exc
