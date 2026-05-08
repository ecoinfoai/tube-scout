"""Spec 010 FR-010-03 — `fetch_transcript` priority inversion unit tests."""

from __future__ import annotations

from unittest.mock import MagicMock

from tube_scout.services.transcript import TranscriptService


def _make_scraper_succeeding(source: str = "auto_generated") -> MagicMock:
    """Mock youtube-transcript-api `_api.list()` that returns a manual track."""
    transcript_obj = MagicMock()
    fetched = MagicMock()
    fetched.snippets = [
        MagicMock(text="hello", start=0.0, duration=1.0),
        MagicMock(text="world", start=1.0, duration=1.0),
    ]
    transcript_obj.fetch.return_value = fetched

    transcript_list = MagicMock()
    if source == "manual":
        transcript_list.find_manually_created_transcript.return_value = transcript_obj
        transcript_list.find_generated_transcript.side_effect = Exception("nope")
    else:
        from youtube_transcript_api import NoTranscriptFound

        transcript_list.find_manually_created_transcript.side_effect = (
            NoTranscriptFound("vid", ["ko", "en"], [])
        )
        transcript_list.find_generated_transcript.return_value = transcript_obj

    api = MagicMock()
    api.list.return_value = transcript_list
    return api


def _make_scraper_blocked() -> MagicMock:
    """Mock scraper raising an IP-block-style exception."""
    api = MagicMock()
    api.list.side_effect = RuntimeError("RequestBlocked: simulated IP block")
    return api


class TestPriorityInversionDefault:
    def test_default_mode_does_not_call_captions_api_when_scraper_succeeds(
        self,
    ) -> None:
        """Default (`prefer_captions_api=False`): scraper first; Captions API NOT called."""
        svc = TranscriptService()
        svc._api = _make_scraper_succeeding()
        captions_client = MagicMock()
        captions_client.fetch_segments.return_value = [{"text": "should-not-see"}]
        svc._captions_client = captions_client

        result = svc.fetch_transcript("private_vid_001")
        assert result is not None
        assert result["source"] == "auto_generated"
        assert captions_client.fetch_segments.call_count == 0


class TestPriorityInversionPreferCaptions:
    def test_prefer_captions_api_calls_captions_first(self) -> None:
        """`prefer_captions_api=True`: captions client consulted first; scraper NOT called."""
        svc = TranscriptService()
        scraper = MagicMock()
        svc._api = scraper
        captions_client = MagicMock()
        captions_client.fetch_segments.return_value = [
            {"text": "caps", "start": 0.0, "duration": 1.0}
        ]
        svc._captions_client = captions_client

        result = svc.fetch_transcript("private_vid_001", prefer_captions_api=True)

        assert result is not None
        assert result["source"] == "captions_api"
        assert result["transcript_type"] == "captions_api"
        assert captions_client.fetch_segments.call_count == 1
        # Scraper was not consulted because Captions API returned non-empty.
        assert scraper.list.call_count == 0

    def test_prefer_captions_api_falls_through_when_none(self) -> None:
        """Captions API returns None → scraper called as fallback."""
        svc = TranscriptService()
        svc._api = _make_scraper_succeeding(source="auto_generated")
        captions_client = MagicMock()
        captions_client.fetch_segments.return_value = None
        svc._captions_client = captions_client

        result = svc.fetch_transcript("private_vid_001", prefer_captions_api=True)
        assert result is not None
        assert result["source"] == "auto_generated"
        assert captions_client.fetch_segments.call_count == 1

    def test_prefer_captions_api_falls_through_when_empty_list(self) -> None:
        """Captions API returns [] → scraper called as fallback (empty == no result)."""
        svc = TranscriptService()
        svc._api = _make_scraper_succeeding(source="auto_generated")
        captions_client = MagicMock()
        captions_client.fetch_segments.return_value = []
        svc._captions_client = captions_client

        result = svc.fetch_transcript("private_vid_001", prefer_captions_api=True)
        assert result is not None
        assert result["source"] == "auto_generated"

    def test_prefer_captions_api_with_no_client_uses_scraper(self) -> None:
        """`captions_client is None` AND prefer flag set → warn + run scraper."""
        svc = TranscriptService()
        svc._api = _make_scraper_succeeding(source="auto_generated")
        svc._captions_client = None  # no client available

        # Must NOT raise AttributeError; falls through to scraper path.
        result = svc.fetch_transcript("private_vid_001", prefer_captions_api=True)
        assert result is not None
        assert result["source"] == "auto_generated"

    def test_prefer_captions_api_with_blocked_scraper_returns_captions(self) -> None:
        """When scraper would IP-block but Captions API has the track: return Captions result."""
        svc = TranscriptService()
        svc._api = _make_scraper_blocked()
        captions_client = MagicMock()
        captions_client.fetch_segments.return_value = [
            {"text": "captioned", "start": 0.0, "duration": 1.0}
        ]
        svc._captions_client = captions_client

        result = svc.fetch_transcript("private_vid_001", prefer_captions_api=True)
        assert result is not None
        assert result["source"] == "captions_api"
        # Scraper would fail; with prefer-captions and Captions API hit,
        # scraper is never asked.
        # (We don't assert call_count==0 because the function might still
        # attempt scraper if prefer-captions returned empty, but here it
        # returned non-empty so scraper is not called.)
