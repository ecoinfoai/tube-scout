"""Contract tests — text_normalizer service (spec 013 T046 RED).

FR-024~FR-026: normalize_transcript_text, normalize_transcript_json, detect_source_conflict.
Module does not exist yet — all tests should fail at import.
"""

from __future__ import annotations

import json
import unicodedata
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# T046-1: normalize_transcript_text is idempotent n(n(x)) == n(x)
# ---------------------------------------------------------------------------

def test_normalize_transcript_text_is_idempotent() -> None:
    """Applying normalize_transcript_text twice yields the same result."""
    from tube_scout.services.text_normalizer import normalize_transcript_text

    inputs = [
        "안녕하세요! [음악] 오늘 강의입니다.",
        "Hello World... This is a TEST.",
        "  공백이  많은   텍스트\n줄바꿈",
        "",
        "♪ 배경음악 ♪ 강의입니다",
    ]
    for text in inputs:
        once = normalize_transcript_text(text)
        twice = normalize_transcript_text(once)
        assert once == twice, (
            f"normalize_transcript_text is not idempotent for: {text!r}\n"
            f"  n(x)   = {once!r}\n"
            f"  n(n(x)) = {twice!r}"
        )


# ---------------------------------------------------------------------------
# T046-2: normalize strips ASR meta-markers
# ---------------------------------------------------------------------------

def test_normalize_strips_meta_markers() -> None:
    """normalize_transcript_text removes [음악], [박수], (...), <...>, *...*, ♪...♪."""
    from tube_scout.services.text_normalizer import normalize_transcript_text

    cases = [
        ("[음악] 안녕하세요", "안녕하세요"),
        ("[박수] 감사합니다", "감사합니다"),
        ("(배경음) 시작합니다", "시작합니다"),
        ("<inaudible> 다음은", "다음은"),
        ("*강조* 텍스트", "텍스트"),
        ("♪ 음악 ♪ 강의", "강의"),
    ]
    for raw, expected in cases:
        result = normalize_transcript_text(raw)
        assert result == expected, (
            f"Meta marker not stripped. Input: {raw!r}, got: {result!r}, expected: {expected!r}"
        )


# ---------------------------------------------------------------------------
# T046-3: normalize strips punctuation
# ---------------------------------------------------------------------------

def test_normalize_strips_punctuation() -> None:
    """normalize_transcript_text removes . , ? ! ~ … and common quote marks."""
    from tube_scout.services.text_normalizer import normalize_transcript_text

    text = "안녕하세요. 오늘은, 무엇을 배울까요? 정말! 좋아요~"
    result = normalize_transcript_text(text)
    for char in ".?!,~":
        assert char not in result, f"Punctuation '{char}' not stripped from: {result!r}"


# ---------------------------------------------------------------------------
# T046-4: NFC normalization for isolated jamo
# ---------------------------------------------------------------------------

def test_normalize_nfc_handles_jamo_isolated() -> None:
    """normalize_transcript_text applies NFC normalization (decomposes → composed)."""
    from tube_scout.services.text_normalizer import normalize_transcript_text

    # NFD form of 가 (decomposed into ㄱ + ㅏ)
    nfd_text = unicodedata.normalize("NFD", "가나다")
    result = normalize_transcript_text(nfd_text)
    expected = unicodedata.normalize("NFC", "가나다")
    assert result == expected, (
        f"NFC normalization failed. Got: {result!r}, expected: {expected!r}"
    )


# ---------------------------------------------------------------------------
# T046-5: lowercase Latin only (Korean unaffected)
# ---------------------------------------------------------------------------

def test_normalize_lowercases_latin_only() -> None:
    """normalize_transcript_text lowercases Latin chars only; Korean chars unchanged."""
    from tube_scout.services.text_normalizer import normalize_transcript_text

    text = "안녕하세요 HELLO WORLD 반갑습니다"
    result = normalize_transcript_text(text)
    assert "hello" in result, f"Latin uppercase not lowercased: {result!r}"
    assert "world" in result, f"Latin uppercase not lowercased: {result!r}"
    assert "안녕하세요" in result, f"Korean text must not be affected: {result!r}"
    assert "반갑습니다" in result, f"Korean text must not be affected: {result!r}"


# ---------------------------------------------------------------------------
# T046-6: whitespace collapse
# ---------------------------------------------------------------------------

def test_normalize_collapses_whitespace_and_newlines() -> None:
    """normalize_transcript_text collapses \\s+ to single space and strips edges."""
    from tube_scout.services.text_normalizer import normalize_transcript_text

    text = "  안녕   하세요\n\n강의입니다   "
    result = normalize_transcript_text(text)
    assert "\n" not in result, f"Newlines not removed: {result!r}"
    assert "  " not in result, f"Double spaces not collapsed: {result!r}"
    assert not result.startswith(" "), f"Leading space not stripped: {result!r}"
    assert not result.endswith(" "), f"Trailing space not stripped: {result!r}"


# ---------------------------------------------------------------------------
# T046-7: normalize_transcript_json writes atomically
# ---------------------------------------------------------------------------

def test_normalize_transcript_json_writes_atomic(tmp_path: Path) -> None:
    """normalize_transcript_json writes output via atomic tempfile+rename, returns True."""
    from tube_scout.services.text_normalizer import normalize_transcript_json

    raw_path = tmp_path / "raw.json"
    norm_path = tmp_path / "normalized.json"

    raw_path.write_text(json.dumps({
        "video_id": "testVID001",
        "source": "whisper",
        "segments": [
            {"start": 0.0, "end": 2.0, "text": "안녕하세요! [음악]"},
        ],
    }), encoding="utf-8")

    result = normalize_transcript_json(raw_path, norm_path)

    assert result is True, "normalize_transcript_json must return True when writing"
    assert norm_path.exists(), "Normalized output file must exist after write"

    data = json.loads(norm_path.read_text(encoding="utf-8"))
    assert data["video_id"] == "testVID001"
    assert "normalizer_version" in data
    assert data["source_type"] == "asr"
    assert len(data["segments"]) == 1


# ---------------------------------------------------------------------------
# T046-8: normalize_transcript_json skips when version matches
# ---------------------------------------------------------------------------

def test_normalize_transcript_json_skips_when_version_matches(tmp_path: Path) -> None:
    """normalize_transcript_json returns False (skip) when output normalizer_version matches."""
    from tube_scout.services.text_normalizer import normalize_transcript_json, NORMALIZER_VERSION

    raw_path = tmp_path / "raw.json"
    norm_path = tmp_path / "normalized.json"

    raw_path.write_text(json.dumps({
        "video_id": "testVID002",
        "source": "captions_api",
        "segments": [{"start": 0.0, "end": 1.0, "text": "테스트"}],
    }), encoding="utf-8")

    # Write once
    normalize_transcript_json(raw_path, norm_path)

    # Second call should skip
    mtime_before = norm_path.stat().st_mtime
    import time; time.sleep(0.01)
    result = normalize_transcript_json(raw_path, norm_path, force=False)

    assert result is False, "normalize_transcript_json must return False when skipping"
    assert norm_path.stat().st_mtime == mtime_before, "File must not be modified on skip"


# ---------------------------------------------------------------------------
# T046-9: normalize_transcript_json force=True rewrites
# ---------------------------------------------------------------------------

def test_normalize_transcript_json_force_rewrites(tmp_path: Path) -> None:
    """normalize_transcript_json returns True when force=True even if output exists."""
    from tube_scout.services.text_normalizer import normalize_transcript_json

    raw_path = tmp_path / "raw.json"
    norm_path = tmp_path / "normalized.json"

    raw_path.write_text(json.dumps({
        "video_id": "testVID003",
        "source": "whisper",
        "segments": [{"start": 0.0, "end": 1.0, "text": "강의"}],
    }), encoding="utf-8")

    normalize_transcript_json(raw_path, norm_path)
    result = normalize_transcript_json(raw_path, norm_path, force=True)

    assert result is True, "normalize_transcript_json must return True when force=True"
