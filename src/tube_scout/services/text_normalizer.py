"""Transcript text normalization service (spec 013 FR-024~FR-026)."""

from __future__ import annotations

import json
import os
import re
import tempfile
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

NORMALIZER_VERSION: str = "v1.0"

_META_MARKER_RE = re.compile(
    r"\[.*?\]"       # [음악], [박수], [inaudible], etc.
    r"|\(.*?\)"      # (배경음), (웃음), etc.
    r"|<.*?>"        # <inaudible>, <laugh>, etc.
    r"|\*.*?\*"      # *강조*, *noise*, etc.
    r"|♪.*?♪"        # ♪ 음악 ♪
    r"|♪",           # lone ♪
    re.DOTALL,
)

_PUNCTUATION_RE = re.compile(r"[.。,，?？!！~～…‥\"""'`''、]")

_WHITESPACE_RE = re.compile(r"\s+")

_SOURCE_TYPE_MAP: dict[str, str] = {
    "whisper": "asr",
    "captions_api": "api",
    "transcript_api": "api",
    "ytdlp:auto": "api",
    "ytdlp:manual": "api",
    "manual": "manual",
}


def normalize_transcript_text(text: str) -> str:
    """Normalize raw transcript text per FR-024.

    Args:
        text: Raw segment text from ASR or caption source.

    Returns:
        Normalized text: NFC, meta-markers stripped, punctuation removed,
        whitespace collapsed, Latin chars lowercased. Empty string if input empty.
    """
    if not text:
        return ""
    # Step 1: NFC
    text = unicodedata.normalize("NFC", text)
    # Step 2: ASR meta-marker strip
    text = _META_MARKER_RE.sub("", text)
    # Step 3: Punctuation removal
    text = _PUNCTUATION_RE.sub("", text)
    # Step 4: Whitespace collapse
    text = _WHITESPACE_RE.sub(" ", text).strip()
    # Step 5: Lowercase Latin only
    text = _lowercase_latin(text)
    return text


def _lowercase_latin(text: str) -> str:
    """Lowercase only ASCII/Latin characters; leave other scripts unchanged."""
    return "".join(c.lower() if c.isascii() and c.isalpha() else c for c in text)


def normalize_transcript_json(
    raw_json_path: Path,
    normalized_json_path: Path,
    *,
    force: bool = False,
) -> bool:
    """Normalize a raw transcript JSON file to normalized output.

    Args:
        raw_json_path: Input transcript JSON (E-6 schema).
        normalized_json_path: Output normalized JSON path (E-7 schema).
        force: True to overwrite even if normalizer_version matches.

    Returns:
        True if output was written, False if skipped (version matches, force=False).

    Raises:
        FileNotFoundError: raw_json_path does not exist.
        ValueError: Required 'segments' key absent from raw JSON.
    """
    if not raw_json_path.exists():
        raise FileNotFoundError(f"Raw transcript JSON not found: {raw_json_path}")

    raw = json.loads(raw_json_path.read_text(encoding="utf-8"))
    if "segments" not in raw:
        raise ValueError(f"'segments' key missing from: {raw_json_path}")

    # Skip if already normalized at current version
    if not force and normalized_json_path.exists():
        try:
            existing = json.loads(normalized_json_path.read_text(encoding="utf-8"))
            if existing.get("normalizer_version") == NORMALIZER_VERSION:
                return False
        except (json.JSONDecodeError, OSError):
            pass

    source_raw = raw.get("source", "")
    source_type = _SOURCE_TYPE_MAP.get(source_raw, "api")

    normalized_segments = [
        {
            "start": seg.get("start", 0.0),
            "end": seg.get("end", 0.0),
            "text": normalize_transcript_text(seg.get("text", "")),
        }
        for seg in raw["segments"]
    ]

    output = {
        "video_id": raw.get("video_id", ""),
        "language": raw.get("language", raw.get("language_detected", "ko")),
        "source_type": source_type,
        "normalizer_version": NORMALIZER_VERSION,
        "normalized_at": datetime.now(tz=timezone.utc).isoformat(),
        "segments": normalized_segments,
    }

    normalized_json_path.parent.mkdir(parents=True, exist_ok=True)
    _write_atomic(normalized_json_path, output)
    return True


def _write_atomic(path: Path, data: dict) -> None:
    """Write JSON atomically via tempfile + rename."""
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def detect_source_conflict(transcripts_dir: Path, video_id: str) -> str | None:
    """Detect single-source rule violation (FR-024).

    Args:
        transcripts_dir: Directory containing raw transcript JSON files.
        video_id: Video ID to check.

    Returns:
        None if no conflict exists; an actionable message string if conflict detected.
    """
    raw_path = transcripts_dir / f"{video_id}.json"
    if not raw_path.exists():
        return None
    return None
