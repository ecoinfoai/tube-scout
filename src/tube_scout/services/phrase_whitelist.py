"""Phrase whitelist service for spec 011 Layer B and Layer D matching.

Currently exposes only the normalize_phrase function (Phase 2B scope).
Additional whitelist CRUD operations are implemented in Phase 6 (T058).
"""

import re
import unicodedata

# Korean and ASCII punctuation to strip (research.md R-7)
_PUNCT_PATTERN = re.compile(
    r"[。、，．・「」『』""''‥…—–·〈〉《》【】｢｣〔〕"
    r',.!?;:()[\]{}\-—–…"\'`~@#$%^&*+=|\\/<>]'
)


def normalize_phrase(text: str) -> str:
    """Apply 5-step normalization for exact-equality phrase comparison.

    Steps (research.md R-7):
      1. Unicode NFKC normalization (full-width → half-width, glyph unification).
      2. casefold (lowercases English; no effect on Korean/CJK).
      3. Punctuation strip — Korean punct + ASCII punct set removed.
      4. Whitespace collapse — any run of whitespace (incl. tab, newline,
         NBSP, IDEOGRAPHIC SPACE) → single ASCII space.
      5. Strip leading/trailing whitespace.

    Args:
        text: Raw phrase or caption segment text to normalize.

    Returns:
        Normalized string suitable for exact-equality comparison.
        Empty string is returned for inputs that are entirely whitespace
        or punctuation.
    """
    # Step 1: NFKC
    normalized = unicodedata.normalize("NFKC", text)
    # Step 2: casefold
    normalized = normalized.casefold()
    # Step 3: strip punctuation
    normalized = _PUNCT_PATTERN.sub(" ", normalized)
    # Step 4: collapse all whitespace variants to single space
    normalized = re.sub(r"\s+", " ", normalized)
    # Step 5: trim
    return normalized.strip()
