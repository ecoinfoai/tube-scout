"""Tests for fingerprint service (SHA-256 hash, embedding generation)."""

import hashlib

import pytest

from tube_scout.services.fingerprint import FingerprintService


class TestFingerprintServiceHash:
    """Tests for SHA-256 fingerprint generation."""

    def test_generates_sha256_hash(self) -> None:
        service = FingerprintService()
        segments = [
            {"text": "hello world", "start": 0.0, "duration": 3.0},
            {"text": "test content", "start": 3.0, "duration": 2.0},
        ]
        fp = service.generate_hash(segments)
        expected_text = "hello world test content"
        expected_hash = hashlib.sha256(expected_text.encode("utf-8")).hexdigest()
        assert fp.sha256_hash == expected_hash
        assert fp.full_text_length == len(expected_text)

    def test_identical_segments_same_hash(self) -> None:
        service = FingerprintService()
        segments = [{"text": "same text", "start": 0.0, "duration": 1.0}]
        fp1 = service.generate_hash(segments)
        fp2 = service.generate_hash(segments)
        assert fp1.sha256_hash == fp2.sha256_hash

    def test_different_segments_different_hash(self) -> None:
        service = FingerprintService()
        fp1 = service.generate_hash([{"text": "text A", "start": 0.0, "duration": 1.0}])
        fp2 = service.generate_hash([{"text": "text B", "start": 0.0, "duration": 1.0}])
        assert fp1.sha256_hash != fp2.sha256_hash

    def test_empty_segments_raises(self) -> None:
        service = FingerprintService()
        with pytest.raises(ValueError, match="segments must not be empty"):
            service.generate_hash([])

    def test_full_text_extraction(self) -> None:
        service = FingerprintService()
        segments = [
            {"text": "  hello  ", "start": 0.0, "duration": 1.0},
            {"text": " world ", "start": 1.0, "duration": 1.0},
        ]
        fp = service.generate_hash(segments)
        # Text is stripped per segment and joined with space
        assert fp.full_text_length == len("hello world")

    def test_korean_text(self) -> None:
        service = FingerprintService()
        segments = [
            {"text": "안녕하세요 여러분", "start": 0.0, "duration": 3.0},
        ]
        fp = service.generate_hash(segments)
        assert fp.sha256_hash == hashlib.sha256("안녕하세요 여러분".encode()).hexdigest()


class TestFingerprintServiceFullText:
    """Tests for full text extraction from segments."""

    def test_extract_full_text(self) -> None:
        service = FingerprintService()
        segments = [
            {"text": "first", "start": 0.0, "duration": 1.0},
            {"text": "second", "start": 1.0, "duration": 1.0},
            {"text": "third", "start": 2.0, "duration": 1.0},
        ]
        text = service.extract_full_text(segments)
        assert text == "first second third"

    def test_extract_strips_whitespace(self) -> None:
        service = FingerprintService()
        segments = [
            {"text": "  padded  ", "start": 0.0, "duration": 1.0},
        ]
        text = service.extract_full_text(segments)
        assert text == "padded"

    def test_extract_skips_empty_segments(self) -> None:
        service = FingerprintService()
        segments = [
            {"text": "keep", "start": 0.0, "duration": 1.0},
            {"text": "  ", "start": 1.0, "duration": 1.0},
            {"text": "this", "start": 2.0, "duration": 1.0},
        ]
        text = service.extract_full_text(segments)
        assert text == "keep this"
