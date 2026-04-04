"""Tests for TranscriptService."""

from unittest.mock import MagicMock, patch

from tube_scout.models.config import RateLimitProfile
from tube_scout.services.rate_limiter import RateLimiter
from tube_scout.services.transcript import TranscriptService


class TestTranscriptServiceRateLimiter:
    """Tests for TranscriptService rate limiter integration (US2)."""

    @patch("tube_scout.services.transcript.YouTubeTranscriptApi")
    def test_wait_called_before_request(
        self, mock_api_cls: MagicMock
    ) -> None:
        """RateLimiter.wait() should be called before each transcript fetch."""
        mock_instance = mock_api_cls.return_value
        tlist = mock_instance.list.return_value
        tlist.find_manually_created_transcript.return_value.fetch.return_value = [
            {"text": "Hello", "start": 0.0, "duration": 2.0},
        ]

        mock_limiter = MagicMock(spec=RateLimiter)
        service = TranscriptService(rate_limiter=mock_limiter)
        service.fetch_transcript("vid001")

        mock_limiter.wait.assert_called_once()

    @patch("tube_scout.services.transcript.YouTubeTranscriptApi")
    def test_default_no_rate_limiter(
        self, mock_api_cls: MagicMock
    ) -> None:
        """TranscriptService should work without rate_limiter (backward compat)."""
        mock_instance = mock_api_cls.return_value
        tlist = mock_instance.list.return_value
        tlist.find_manually_created_transcript.return_value.fetch.return_value = [
            {"text": "Hello", "start": 0.0, "duration": 2.0},
        ]

        service = TranscriptService()
        result = service.fetch_transcript("vid001")
        assert result is not None

    @patch("tube_scout.services.transcript.YouTubeTranscriptApi")
    def test_configurable_profile(
        self, mock_api_cls: MagicMock
    ) -> None:
        """TranscriptService should accept custom RateLimitProfile via rate_limiter."""
        profile = RateLimitProfile(
            base_delay=5.0, max_retries=10, backoff_multiplier=4.0, jitter=1.0
        )
        limiter = RateLimiter(profile)
        service = TranscriptService(rate_limiter=limiter)
        assert service._rate_limiter is limiter
        assert service._rate_limiter.profile.base_delay == 5.0


class TestTranscriptService:
    """Tests for TranscriptService (T044)."""

    @patch("tube_scout.services.transcript.YouTubeTranscriptApi")
    def test_fetch_manual_transcript(
        self,
        mock_api_cls: MagicMock,
    ) -> None:
        mock_instance = mock_api_cls.return_value
        tlist = mock_instance.list.return_value
        tlist.find_manually_created_transcript.return_value.fetch.return_value = [
            {"text": "Hello", "start": 0.0, "duration": 2.0},
            {"text": "Welcome", "start": 2.0, "duration": 3.0},
        ]
        service = TranscriptService()
        result = service.fetch_transcript("vid001")
        assert result is not None
        assert result["transcript_type"] == "manual"
        assert len(result["segments"]) == 2

    @patch("tube_scout.services.transcript.YouTubeTranscriptApi")
    def test_fetch_auto_generated_fallback(
        self,
        mock_api_cls: MagicMock,
    ) -> None:
        from youtube_transcript_api import NoTranscriptFound

        mock_instance = mock_api_cls.return_value
        tlist = mock_instance.list.return_value
        tlist.find_manually_created_transcript.side_effect = NoTranscriptFound(
            "vid001", ["ko"], None
        )
        tlist.find_generated_transcript.return_value.fetch.return_value = [
            {"text": "Auto text", "start": 0.0, "duration": 5.0},
        ]
        service = TranscriptService()
        result = service.fetch_transcript("vid001")
        assert result is not None
        assert result["transcript_type"] == "auto_generated"

    @patch("tube_scout.services.transcript.YouTubeTranscriptApi")
    def test_no_transcript_returns_none(
        self,
        mock_api_cls: MagicMock,
    ) -> None:
        from youtube_transcript_api import TranscriptsDisabled

        mock_instance = mock_api_cls.return_value
        mock_instance.list.side_effect = TranscriptsDisabled("vid001")
        service = TranscriptService()
        result = service.fetch_transcript("vid001")
        assert result is None

    @patch("tube_scout.services.transcript.YouTubeTranscriptApi")
    def test_language_preference(
        self,
        mock_api_cls: MagicMock,
    ) -> None:
        mock_instance = mock_api_cls.return_value
        tlist = mock_instance.list.return_value
        tlist.find_manually_created_transcript.return_value.fetch.return_value = [
            {"text": "Korean text", "start": 0.0, "duration": 2.0},
        ]
        service = TranscriptService(languages=["ko", "en"])
        result = service.fetch_transcript("vid001")
        assert result is not None

    @patch("tube_scout.services.transcript.YouTubeTranscriptApi")
    def test_whisper_fallback_when_no_transcript(
        self,
        mock_api_cls: MagicMock,
    ) -> None:
        """FR-007: When no transcript, try Whisper STT if available."""
        from youtube_transcript_api import NoTranscriptFound

        mock_instance = mock_api_cls.return_value
        tlist = mock_instance.list.return_value
        tlist.find_manually_created_transcript.side_effect = NoTranscriptFound(
            "vid001", ["ko"], None
        )
        tlist.find_generated_transcript.side_effect = NoTranscriptFound(
            "vid001", ["ko"], None
        )

        mock_whisper = MagicMock()
        mock_model = MagicMock()
        mock_whisper.load_model.return_value = mock_model
        mock_model.transcribe.return_value = {
            "segments": [
                {"text": "Whisper text", "start": 0.0, "end": 5.0},
                {"text": "More text", "start": 5.0, "end": 10.0},
            ]
        }

        with patch.dict(
            "sys.modules",
            {"whisper": mock_whisper},
        ):
            service = TranscriptService()
            result = service.fetch_transcript(
                "vid001",
                audio_path="/tmp/audio.mp3",
            )

        assert result is not None
        assert result["transcript_type"] == "whisper_stt"
        assert len(result["segments"]) == 2
        assert result["segments"][0]["text"] == "Whisper text"

    @patch("tube_scout.services.transcript.YouTubeTranscriptApi")
    def test_whisper_not_installed_graceful_skip(
        self,
        mock_api_cls: MagicMock,
    ) -> None:
        """FR-007: Graceful skip when Whisper is not installed."""
        from youtube_transcript_api import NoTranscriptFound

        mock_instance = mock_api_cls.return_value
        tlist = mock_instance.list.return_value
        tlist.find_manually_created_transcript.side_effect = NoTranscriptFound(
            "vid001", ["ko"], None
        )
        tlist.find_generated_transcript.side_effect = NoTranscriptFound(
            "vid001", ["ko"], None
        )

        with patch.dict("sys.modules", {"whisper": None}):
            service = TranscriptService()
            result = service.fetch_transcript(
                "vid001",
                audio_path="/tmp/audio.mp3",
            )

        assert result is None

    @patch("tube_scout.services.transcript.YouTubeTranscriptApi")
    def test_whisper_no_audio_path_skips(
        self,
        mock_api_cls: MagicMock,
    ) -> None:
        """FR-007: Without audio_path, Whisper fallback not attempted."""
        from youtube_transcript_api import NoTranscriptFound

        mock_instance = mock_api_cls.return_value
        tlist = mock_instance.list.return_value
        tlist.find_manually_created_transcript.side_effect = NoTranscriptFound(
            "vid001", ["ko"], None
        )
        tlist.find_generated_transcript.side_effect = NoTranscriptFound(
            "vid001", ["ko"], None
        )

        service = TranscriptService()
        result = service.fetch_transcript("vid001")
        assert result is None
