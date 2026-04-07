"""Tests for SRT parser utility."""

import pytest

from tube_scout.services.srt_parser import parse_srt


class TestParseSrt:
    """Tests for SRT text parsing."""

    def test_valid_srt_single_segment(self) -> None:
        srt_text = (
            "1\n"
            "00:00:01,000 --> 00:00:05,000\n"
            "Hello world\n"
            "\n"
        )
        segments = parse_srt(srt_text)
        assert len(segments) == 1
        assert segments[0]["text"] == "Hello world"
        assert segments[0]["start"] == pytest.approx(1.0)
        assert segments[0]["duration"] == pytest.approx(4.0)

    def test_valid_srt_multiple_segments(self) -> None:
        srt_text = (
            "1\n"
            "00:00:00,000 --> 00:00:03,500\n"
            "First line\n"
            "\n"
            "2\n"
            "00:00:04,000 --> 00:00:08,200\n"
            "Second line\n"
            "\n"
        )
        segments = parse_srt(srt_text)
        assert len(segments) == 2
        assert segments[0]["text"] == "First line"
        assert segments[0]["start"] == pytest.approx(0.0)
        assert segments[0]["duration"] == pytest.approx(3.5)
        assert segments[1]["text"] == "Second line"
        assert segments[1]["start"] == pytest.approx(4.0)
        assert segments[1]["duration"] == pytest.approx(4.2)

    def test_multi_line_text(self) -> None:
        srt_text = (
            "1\n"
            "00:00:01,000 --> 00:00:05,000\n"
            "Line one\n"
            "Line two\n"
            "\n"
        )
        segments = parse_srt(srt_text)
        assert len(segments) == 1
        assert segments[0]["text"] == "Line one\nLine two"

    def test_empty_srt(self) -> None:
        segments = parse_srt("")
        assert segments == []

    def test_whitespace_only_srt(self) -> None:
        segments = parse_srt("   \n\n  \n")
        assert segments == []

    def test_malformed_timestamp_skipped(self) -> None:
        srt_text = (
            "1\n"
            "INVALID TIMESTAMP\n"
            "Some text\n"
            "\n"
            "2\n"
            "00:00:01,000 --> 00:00:02,000\n"
            "Valid text\n"
            "\n"
        )
        segments = parse_srt(srt_text)
        assert len(segments) == 1
        assert segments[0]["text"] == "Valid text"

    def test_korean_text(self) -> None:
        srt_text = (
            "1\n"
            "00:00:00,000 --> 00:00:03,000\n"
            "안녕하세요 여러분\n"
            "\n"
        )
        segments = parse_srt(srt_text)
        assert len(segments) == 1
        assert segments[0]["text"] == "안녕하세요 여러분"

    def test_hour_timestamps(self) -> None:
        srt_text = (
            "1\n"
            "01:30:00,000 --> 01:30:10,500\n"
            "Late in lecture\n"
            "\n"
        )
        segments = parse_srt(srt_text)
        assert len(segments) == 1
        assert segments[0]["start"] == pytest.approx(5400.0)
        assert segments[0]["duration"] == pytest.approx(10.5)

    def test_no_trailing_newline(self) -> None:
        srt_text = (
            "1\n"
            "00:00:01,000 --> 00:00:02,000\n"
            "No trailing newline"
        )
        segments = parse_srt(srt_text)
        assert len(segments) == 1
        assert segments[0]["text"] == "No trailing newline"

    def test_bom_prefix_handled(self) -> None:
        srt_text = (
            "\ufeff1\n"
            "00:00:00,000 --> 00:00:01,000\n"
            "BOM text\n"
            "\n"
        )
        segments = parse_srt(srt_text)
        assert len(segments) == 1
        assert segments[0]["text"] == "BOM text"
