"""Fingerprint service for caption text hashing and embedding generation.

Generates SHA-256 hashes from full caption text and optionally creates
semantic embeddings using sentence-transformers for similarity comparison.
"""

import hashlib
import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class HashFingerprint:
    """Result of SHA-256 hash generation.

    Attributes:
        sha256_hash: SHA-256 hex digest of the full text.
        full_text_length: Character count of the full text.
    """

    sha256_hash: str
    full_text_length: int


class FingerprintService:
    """Service for generating content fingerprints from caption segments.

    Provides SHA-256 hashing for exact-match detection and full-text
    extraction for downstream embedding and comparison operations.
    """

    def extract_full_text(self, segments: list[dict[str, Any]]) -> str:
        """Extract and concatenate text from caption segments.

        Strips whitespace per segment and joins with single space.
        Empty/whitespace-only segments are skipped.

        Args:
            segments: List of segment dicts with 'text' key.

        Returns:
            Concatenated full text string.
        """
        parts: list[str] = []
        for seg in segments:
            text = seg.get("text", "").strip()
            if text:
                parts.append(text)
        return " ".join(parts)

    def generate_hash(self, segments: list[dict[str, Any]]) -> HashFingerprint:
        """Generate SHA-256 hash fingerprint from caption segments.

        Args:
            segments: List of segment dicts with 'text' key.

        Returns:
            HashFingerprint with sha256_hash and full_text_length.

        Raises:
            ValueError: If segments list is empty.
        """
        if not segments:
            raise ValueError("segments must not be empty")

        full_text = self.extract_full_text(segments)
        sha256_hash = hashlib.sha256(full_text.encode("utf-8")).hexdigest()

        return HashFingerprint(
            sha256_hash=sha256_hash,
            full_text_length=len(full_text),
        )
