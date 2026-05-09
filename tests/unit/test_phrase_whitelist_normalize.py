"""Unit tests for phrase_whitelist.normalize_phrase (T013 RED).

Tests verify the 5-step normalization pipeline: NFKC → casefold →
punct strip → whitespace collapse → trim (research.md R-7).
"""

from tube_scout.services.phrase_whitelist import normalize_phrase


def test_nfkc_unifies_fullwidth() -> None:
    """Full-width ASCII letters are converted to half-width and lowercased."""
    assert normalize_phrase("ＡＢＣ") == "abc"


def test_punctuation_stripped() -> None:
    """ASCII punctuation is removed and surrounding space collapsed."""
    result = normalize_phrase("안녕하세요, 박정광입니다.")
    assert result == "안녕하세요 박정광입니다"


def test_whitespace_collapsed() -> None:
    """Multiple whitespace characters (including tabs) collapse to single space."""
    result = normalize_phrase("안녕   하세요\t박정광")
    assert result == "안녕 하세요 박정광"


def test_korean_punct_stripped() -> None:
    """Korean punctuation marks are removed."""
    result = normalize_phrase("오늘은 「감염미생물학」 입니다。")
    assert result == "오늘은 감염미생물학 입니다"


def test_idempotent() -> None:
    """Applying normalize_phrase twice yields the same result as once."""
    text = "오늘 「배울」 내용은, 미생물 분류입니다。  "
    once = normalize_phrase(text)
    twice = normalize_phrase(once)
    assert once == twice


def test_empty_string() -> None:
    """Empty string normalizes to empty string."""
    assert normalize_phrase("") == ""


def test_only_whitespace() -> None:
    """String containing only whitespace normalizes to empty string."""
    assert normalize_phrase("  \t\n  ") == ""


def test_korean_no_case_change() -> None:
    """Korean characters are unaffected by casefold."""
    text = "안녕하세요"
    assert normalize_phrase(text) == text
