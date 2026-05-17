"""RED tests for ChannelMetadata + VideoMetadata Pydantic models (spec 013 T012).

Ref: data-model.md §E-1, §E-2.
"""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from tube_scout.models.content import ChannelMetadata, VideoMetadata

_NOW = datetime(2026, 5, 13, 10, 30, 0, tzinfo=UTC)


def test_channel_metadata_round_trip_json() -> None:
    """ChannelMetadata must survive a dump-then-parse round-trip."""
    ch = ChannelMetadata(
        channel_id="UCxxxxxxxxxxxxxxxxxxxxxx",
        channel_alias="nursing",
        title="간호학과 채널",
        country="KR",
        privacy_status="unlisted",
        source="takeout",
        takeout_root_hint="/data/takeout-001",
        ingested_at=_NOW,
    )
    restored = ChannelMetadata.model_validate_json(ch.model_dump_json())
    assert restored.channel_id == ch.channel_id
    assert restored.channel_alias == ch.channel_alias
    assert restored.privacy_status == ch.privacy_status
    assert restored.source == ch.source
    assert restored.ingested_at == ch.ingested_at


def test_video_metadata_match_confidence_literal() -> None:
    """match_confidence accepts only high/medium/ambiguous/None; rejects other strings."""
    base = dict(
        video_id="dQw4w9WgXcQ",
        channel_id="UC12345",
        title="Test Video",
        source="takeout",
        ingested_at=_NOW,
    )
    for valid in ("high", "medium", "ambiguous", None):
        vm = VideoMetadata(**base, match_confidence=valid)
        assert vm.match_confidence == valid

    with pytest.raises(ValidationError):
        VideoMetadata(**base, match_confidence="unknown")


def test_video_metadata_privacy_status_literal() -> None:
    """privacy_status accepts only public/unlisted/private/None; rejects other strings."""
    base = dict(
        video_id="dQw4w9WgXcQ",
        channel_id="UC12345",
        title="Test Video",
        source="takeout",
        ingested_at=_NOW,
    )
    for valid in ("public", "unlisted", "private", None):
        vm = VideoMetadata(**base, privacy_status=valid)
        assert vm.privacy_status == valid

    with pytest.raises(ValidationError):
        VideoMetadata(**base, privacy_status="restricted")
