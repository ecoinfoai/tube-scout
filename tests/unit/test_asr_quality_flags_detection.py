"""Unit tests — ASR quality flag detection helpers (spec 013 T043 RED).

FR-017/FR-021: detect_quality_flags and its sub-detectors.
Module does not exist yet — all tests should fail at import.
"""

from __future__ import annotations


def _seg(text: str, start: float = 0.0, end: float = 1.0) -> dict:
    return {"start": start, "end": end, "text": text}


# ---------------------------------------------------------------------------
# T043-1: _detect_repeat_n finds 3 consecutive identical segments
# ---------------------------------------------------------------------------

def test_detect_repeat_n_finds_3_consecutive() -> None:
    """_detect_repeat_n returns True when 3+ consecutive segments have identical text."""
    from tube_scout.services.asr import _detect_repeat_n

    segments = [
        _seg("안녕하세요", 0.0, 1.0),
        _seg("반복 텍스트", 1.0, 2.0),
        _seg("반복 텍스트", 2.0, 3.0),
        _seg("반복 텍스트", 3.0, 4.0),
        _seg("다른 텍스트", 4.0, 5.0),
    ]
    assert _detect_repeat_n(segments, n=3) is True


def test_detect_repeat_n_no_repeat() -> None:
    """_detect_repeat_n returns False when no 3 consecutive segments are identical."""
    from tube_scout.services.asr import _detect_repeat_n

    segments = [
        _seg("첫번째", 0.0, 1.0),
        _seg("두번째", 1.0, 2.0),
        _seg("첫번째", 2.0, 3.0),
        _seg("세번째", 3.0, 4.0),
    ]
    assert _detect_repeat_n(segments, n=3) is False


def test_detect_repeat_n_exactly_2_consecutive_not_triggered() -> None:
    """_detect_repeat_n(n=3) returns False when only 2 consecutive identical."""
    from tube_scout.services.asr import _detect_repeat_n

    segments = [
        _seg("동일한 텍스트", 0.0, 1.0),
        _seg("동일한 텍스트", 1.0, 2.0),
        _seg("다른 텍스트", 2.0, 3.0),
    ]
    assert _detect_repeat_n(segments, n=3) is False


# ---------------------------------------------------------------------------
# T043-2: _detect_silence_filler finds Korean silence hallucination patterns
# ---------------------------------------------------------------------------

def test_detect_silence_filler_finds_common_patterns() -> None:
    """_detect_silence_filler returns True for at least 5 known hallucination patterns."""
    from tube_scout.services.asr import _detect_silence_filler

    known_patterns = [
        "구독과 좋아요",
        "시청해주셔서 감사합니다",
        "구독 부탁드립니다",
        "좋아요와 구독",
        "알림 설정",
    ]

    for pattern in known_patterns:
        segments = [_seg(pattern, 0.0, 1.0)]
        assert _detect_silence_filler(segments) is True, (
            f"_detect_silence_filler must detect hallucination pattern: '{pattern}'"
        )


def test_detect_silence_filler_clean_text_returns_false() -> None:
    """_detect_silence_filler returns False for normal lecture content."""
    from tube_scout.services.asr import _detect_silence_filler

    segments = [
        _seg("오늘 강의는 파이썬 기초입니다", 0.0, 2.0),
        _seg("변수와 자료형에 대해 알아보겠습니다", 2.0, 5.0),
    ]
    assert _detect_silence_filler(segments) is False


# ---------------------------------------------------------------------------
# T043-3: language_mismatch triggers when detected differs from expected
# ---------------------------------------------------------------------------

def test_language_mismatch_triggers_when_detected_differs() -> None:
    """detect_quality_flags sets language_mismatch=True when language_detected != expected."""
    from tube_scout.services.asr import detect_quality_flags

    segments = [_seg("hello world", 0.0, 1.0)]
    flags = detect_quality_flags(
        segments=segments,
        language_detected="en",
        expected_lang="ko",
        audio_duration=1.0,
    )
    assert flags.language_mismatch is True


def test_language_mismatch_false_when_matches() -> None:
    """detect_quality_flags sets language_mismatch=False when language matches."""
    from tube_scout.services.asr import detect_quality_flags

    segments = [_seg("안녕하세요", 0.0, 1.0)]
    flags = detect_quality_flags(
        segments=segments,
        language_detected="ko",
        expected_lang="ko",
        audio_duration=1.0,
    )
    assert flags.language_mismatch is False


# ---------------------------------------------------------------------------
# T043-4: short_segments_excess_ratio threshold
# ---------------------------------------------------------------------------

def test_short_segments_excess_ratio_threshold() -> None:
    """detect_quality_flags sets short_segments_excess=True when >30% segments are <0.5s."""
    from tube_scout.services.asr import detect_quality_flags

    # 4 of 5 segments are <0.5s → 80% ratio, well above 30% threshold
    segments = [
        _seg("a", 0.0, 0.3),
        _seg("b", 0.3, 0.6),
        _seg("c", 0.6, 0.9),
        _seg("d", 0.9, 1.2),
        _seg("this is a normal length segment", 1.2, 5.0),
    ]
    flags = detect_quality_flags(
        segments=segments,
        language_detected="ko",
        expected_lang="ko",
        audio_duration=5.0,
    )
    assert flags.short_segments_excess is True


def test_short_segments_excess_false_when_below_threshold() -> None:
    """detect_quality_flags sets short_segments_excess=False when ratio below threshold."""
    from tube_scout.services.asr import detect_quality_flags

    segments = [
        _seg("정상적인 길이의 강의 내용입니다", 0.0, 3.0),
        _seg("두 번째 세그먼트도 정상 길이입니다", 3.0, 6.0),
        _seg("세 번째 세그먼트", 6.0, 9.0),
        _seg("짧음", 9.0, 9.3),
    ]
    flags = detect_quality_flags(
        segments=segments,
        language_detected="ko",
        expected_lang="ko",
        audio_duration=9.3,
    )
    assert flags.short_segments_excess is False


# ---------------------------------------------------------------------------
# T043-5: compression_ratio_violations counter
# ---------------------------------------------------------------------------

def test_compression_ratio_violations_counter() -> None:
    """detect_quality_flags counts compression_ratio_violations from segment metadata."""
    from tube_scout.services.asr import detect_quality_flags

    # Segments with compression_ratio field simulating violations
    segments_with_cr = [
        {"start": 0.0, "end": 1.0, "text": "ok", "compression_ratio": 1.5},
        {"start": 1.0, "end": 2.0, "text": "violation", "compression_ratio": 3.0},
        {"start": 2.0, "end": 3.0, "text": "also violation", "compression_ratio": 2.5},
        {"start": 3.0, "end": 4.0, "text": "ok again", "compression_ratio": 1.8},
    ]
    flags = detect_quality_flags(
        segments=segments_with_cr,
        language_detected="ko",
        expected_lang="ko",
        audio_duration=4.0,
    )
    assert flags.compression_ratio_violations == 2, (
        f"Expected 2 compression violations (>2.4), got {flags.compression_ratio_violations}"
    )
