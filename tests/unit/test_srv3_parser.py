"""T015 RED — srv3_to_transcript_json 7 scenarios."""
import datetime
from pathlib import Path

import pytest

FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "spec012"
AUTO_FIXTURE = FIXTURE_DIR / "auto_track.ko-orig.srv3"


def _minimal_srv3(inner_body: str) -> str:
    return f'<?xml version="1.0" encoding="utf-8" ?><timedtext format="3"><body>{inner_body}</body></timedtext>'


@pytest.fixture
def auto_srv3_text() -> str:
    return AUTO_FIXTURE.read_text(encoding="utf-8")


def test_fixture_767_segments(auto_srv3_text: str) -> None:
    """Scenario 1: full fixture → 767 segments, correct start/end."""
    from tube_scout.services.srv3_parser import srv3_to_transcript_json

    result = srv3_to_transcript_json(auto_srv3_text, video_id="FIXTURE_VID", source="ytdlp:auto")

    assert result["video_id"] == "FIXTURE_VID"
    assert result["language"] == "ko"
    assert result["source"] == "ytdlp:auto"
    # fetched_at must be ISO 8601 timezone-aware
    dt = datetime.datetime.fromisoformat(result["fetched_at"])
    assert dt.tzinfo is not None

    segs = result["segments"]
    assert len(segs) == 767
    assert segs[0]["start"] == pytest.approx(3.3, abs=0.001)
    assert segs[-1]["end"] == pytest.approx(1982.299, abs=0.001)
    for seg in segs:
        assert isinstance(seg["text"], str) and seg["text"].strip() != ""


def test_rolling_display_skip() -> None:
    """Scenario 2: <p a="1"> rolling duplicate is skipped."""
    from tube_scout.services.srv3_parser import srv3_to_transcript_json

    xml_body = (
        '<p t="100" d="200" a="1"><s>예고</s></p>'
        '<p t="100" d="200"><s>예고</s></p>'
    )
    result = srv3_to_transcript_json(_minimal_srv3(xml_body), video_id="TEST0000001")
    assert len(result["segments"]) == 1
    assert result["segments"][0]["text"] == "예고"


def test_empty_p_skip() -> None:
    """Scenario 3: empty <p> (whitespace-only text) is skipped."""
    from tube_scout.services.srv3_parser import srv3_to_transcript_json

    xml_body = (
        '<p t="100" d="200"></p>'
        '<p t="300" d="100"><s>실제</s></p>'
    )
    result = srv3_to_transcript_json(_minimal_srv3(xml_body), video_id="TEST0000002")
    assert len(result["segments"]) == 1
    assert result["segments"][0]["text"] == "실제"


def test_p_direct_text_no_s_children() -> None:
    """Scenario 4: <p> with direct text (no <s>) uses p.text."""
    from tube_scout.services.srv3_parser import srv3_to_transcript_json

    xml_body = '<p t="0" d="500">[음악]</p>'
    result = srv3_to_transcript_json(_minimal_srv3(xml_body), video_id="TEST0000003")
    assert len(result["segments"]) == 1
    seg = result["segments"][0]
    assert seg["start"] == pytest.approx(0.0, abs=0.001)
    assert seg["end"] == pytest.approx(0.5, abs=0.001)
    assert seg["text"] == "[음악]"


def test_empty_body_raises_srv3_parse_error() -> None:
    """Scenario 5: empty <body> raises Srv3ParseError."""
    from tube_scout.services.srv3_parser import Srv3ParseError, srv3_to_transcript_json

    xml = "<timedtext><body></body></timedtext>"
    with pytest.raises(Srv3ParseError):
        srv3_to_transcript_json(xml, video_id="TEST0000004")


def test_malformed_xml_raises_srv3_parse_error() -> None:
    """Scenario 6: malformed XML raises Srv3ParseError."""
    from tube_scout.services.srv3_parser import Srv3ParseError, srv3_to_transcript_json

    xml = "<timedtext><body><p t=\"0\">unclosed"
    with pytest.raises(Srv3ParseError):
        srv3_to_transcript_json(xml, video_id="TEST0000005")


def test_utf8_korean_preserved() -> None:
    """Scenario 7: Korean text preserved as-is (no NFC normalization)."""
    from tube_scout.services.srv3_parser import srv3_to_transcript_json

    text = "안녕하세요 홍길동의 교수입니다"
    xml_body = f'<p t="0" d="3000"><s>{text}</s></p>'
    result = srv3_to_transcript_json(_minimal_srv3(xml_body), video_id="TEST0000006")
    assert result["segments"][0]["text"] == text
