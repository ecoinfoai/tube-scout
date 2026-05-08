"""Tests for enhanced TranscriptService with Captions API fallback."""

from unittest.mock import MagicMock, patch

from tube_scout.services.transcript import TranscriptService


class TestTranscriptServiceCaptionsApiFallback:
    """Tests for Captions API fallback when transcript-api fails."""

    def test_public_video_uses_transcript_api(self) -> None:
        """Public videos should use youtube-transcript-api directly."""
        service = TranscriptService()
        mock_fetched = MagicMock()
        mock_fetched.snippets = [
            MagicMock(text="hello", start=0.0, duration=3.0),
        ]
        mock_transcript = MagicMock()
        mock_transcript.fetch.return_value = mock_fetched

        with patch.object(service, "_api") as mock_api:
            mock_list = MagicMock()
            mock_list.find_manually_created_transcript.return_value = mock_transcript
            mock_api.list.return_value = mock_list
            result = service.fetch_transcript("public_video")

        assert result is not None
        assert result["transcript_type"] == "manual"
        assert len(result["segments"]) == 1

    def test_private_video_fallback_to_captions_api(self) -> None:
        """Private videos that fail transcript-api should fall back to Captions API."""
        from youtube_transcript_api import TranscriptsDisabled

        mock_captions_client = MagicMock()
        mock_captions_client.fetch_segments.return_value = [
            {"text": "private content", "start": 0.0, "duration": 5.0},
        ]
        mock_captions_client.quota_used = 250

        service = TranscriptService(captions_api_client=mock_captions_client)

        with patch.object(service, "_api") as mock_api:
            mock_api.list.side_effect = TranscriptsDisabled("vid1")
            result = service.fetch_transcript("vid1")

        assert result is not None
        assert result["transcript_type"] == "captions_api"
        assert result["segments"][0]["text"] == "private content"
        mock_captions_client.fetch_segments.assert_called_once_with("vid1")

    def test_fallback_returns_none_when_no_captions(self) -> None:
        """If both transcript-api and Captions API fail, return None."""
        from youtube_transcript_api import TranscriptsDisabled

        mock_captions_client = MagicMock()
        mock_captions_client.fetch_segments.return_value = None

        service = TranscriptService(captions_api_client=mock_captions_client)

        with patch.object(service, "_api") as mock_api:
            mock_api.list.side_effect = TranscriptsDisabled("vid1")
            result = service.fetch_transcript("vid1")

        assert result is None

    def test_no_captions_client_no_fallback(self) -> None:
        """Without CaptionsAPIClient, transcript-api failure returns None."""
        from youtube_transcript_api import TranscriptsDisabled

        service = TranscriptService()

        with patch.object(service, "_api") as mock_api:
            mock_api.list.side_effect = TranscriptsDisabled("vid1")
            result = service.fetch_transcript("vid1")

        assert result is None

    def test_fallback_on_generic_exception(self) -> None:
        """Captions API fallback should also trigger on generic exceptions."""
        mock_captions_client = MagicMock()
        mock_captions_client.fetch_segments.return_value = [
            {"text": "fallback", "start": 0.0, "duration": 2.0},
        ]

        service = TranscriptService(captions_api_client=mock_captions_client)

        with patch.object(service, "_api") as mock_api:
            mock_api.list.side_effect = Exception("VideoUnplayable")
            result = service.fetch_transcript("vid1")

        assert result is not None
        assert result["transcript_type"] == "captions_api"


class TestTranscriptServiceProcessingStatus:
    """Tests for processing status callback integration."""

    def test_status_callback_called_on_success(self) -> None:
        """Status callback should be called with collected status."""
        status_calls: list[tuple] = []

        def on_status(video_id: str, status: str, source: str | None = None) -> None:
            status_calls.append((video_id, status, source))

        service = TranscriptService(on_status_change=on_status)
        mock_fetched = MagicMock()
        mock_fetched.snippets = [
            MagicMock(text="hello", start=0.0, duration=3.0),
        ]
        mock_transcript = MagicMock()
        mock_transcript.fetch.return_value = mock_fetched

        with patch.object(service, "_api") as mock_api:
            mock_list = MagicMock()
            mock_list.find_manually_created_transcript.return_value = mock_transcript
            mock_api.list.return_value = mock_list
            service.fetch_transcript("vid1")

        assert len(status_calls) == 1
        assert status_calls[0] == ("vid1", "collected", "transcript_api")

    def test_status_callback_called_on_failure(self) -> None:
        """Status callback should be called with no_caption on failure."""
        status_calls: list[tuple] = []

        def on_status(video_id: str, status: str, source: str | None = None) -> None:
            status_calls.append((video_id, status, source))

        from youtube_transcript_api import TranscriptsDisabled

        service = TranscriptService(on_status_change=on_status)

        with patch.object(service, "_api") as mock_api:
            mock_api.list.side_effect = TranscriptsDisabled("vid1")
            service.fetch_transcript("vid1")

        assert len(status_calls) == 1
        assert status_calls[0] == ("vid1", "no_caption", None)

    def test_status_callback_on_captions_api_success(self) -> None:
        """Captions API fallback success should report captions_api source."""
        status_calls: list[tuple] = []

        def on_status(video_id: str, status: str, source: str | None = None) -> None:
            status_calls.append((video_id, status, source))

        from youtube_transcript_api import TranscriptsDisabled

        mock_captions_client = MagicMock()
        mock_captions_client.fetch_segments.return_value = [
            {"text": "ok", "start": 0.0, "duration": 1.0},
        ]

        service = TranscriptService(
            captions_api_client=mock_captions_client,
            on_status_change=on_status,
        )

        with patch.object(service, "_api") as mock_api:
            mock_api.list.side_effect = TranscriptsDisabled("vid1")
            service.fetch_transcript("vid1")

        assert len(status_calls) == 1
        assert status_calls[0] == ("vid1", "collected", "captions_api")
