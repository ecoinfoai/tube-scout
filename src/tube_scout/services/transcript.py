"""Transcript fetching service using youtube-transcript-api."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import requests
from youtube_transcript_api import (
    NoTranscriptFound,
    TranscriptsDisabled,
    YouTubeTranscriptApi,
)

from tube_scout.models.config import DEFAULT_API_TIMEOUT_SECONDS

if TYPE_CHECKING:
    from tube_scout.services.rate_limiter import RateLimiter

logger = logging.getLogger(__name__)


class TranscriptService:
    """Service for fetching video transcripts."""

    def __init__(
        self,
        languages: list[str] | None = None,
        rate_limiter: RateLimiter | None = None,
    ) -> None:
        """Initialize transcript service.

        Args:
            languages: Preferred language codes in order (default: ['ko', 'en']).
            rate_limiter: Optional rate limiter for inter-request delays.
        """
        self.languages = languages or ["ko", "en"]
        session = requests.Session()
        session.timeout = DEFAULT_API_TIMEOUT_SECONDS  # type: ignore[attr-defined]
        self._api = YouTubeTranscriptApi(http_client=session)
        self._rate_limiter = rate_limiter

    def fetch_transcript(
        self,
        video_id: str,
        audio_path: str | None = None,
    ) -> dict[str, Any] | None:
        """Fetch transcript for a video.

        Tries manual transcript first, then auto-generated, then
        optional Whisper STT fallback if audio_path is provided.

        Args:
            video_id: YouTube video ID.
            audio_path: Optional path to audio file for Whisper STT fallback.

        Returns:
            Dict with 'transcript_type' and 'segments', or None if unavailable.
        """
        if self._rate_limiter is not None:
            self._rate_limiter.wait()

        try:
            transcript_list = self._api.list(video_id)
        except TranscriptsDisabled:
            logger.warning("Transcripts disabled for video %s", video_id)
            return None
        except Exception as e:
            logger.warning("Failed to list transcripts for %s: %s", video_id, e)
            return None

        # Try manual transcript first
        try:
            transcript = transcript_list.find_manually_created_transcript(
                self.languages
            )
            fetched = transcript.fetch()
            return {
                "video_id": video_id,
                "transcript_type": "manual",
                "segments": self._to_segments(fetched),
            }
        except NoTranscriptFound:
            pass

        # Fallback to auto-generated
        try:
            transcript = transcript_list.find_generated_transcript(self.languages)
            fetched = transcript.fetch()
            return {
                "video_id": video_id,
                "transcript_type": "auto_generated",
                "segments": self._to_segments(fetched),
            }
        except NoTranscriptFound:
            pass

        # Whisper STT fallback (FR-007)
        if audio_path:
            return self._whisper_fallback(video_id, audio_path)

        logger.warning("No transcript found for video %s", video_id)
        return None

    @staticmethod
    def _to_segments(fetched: Any) -> list[dict[str, Any]]:
        """Convert FetchedTranscript or list of dicts to segment dicts.

        Args:
            fetched: FetchedTranscript object (with .snippets) or list of dicts.

        Returns:
            List of segment dicts with text, start, duration keys.
        """
        snippets = fetched.snippets if hasattr(fetched, "snippets") else fetched
        segments: list[dict[str, Any]] = []
        for s in snippets:
            if isinstance(s, dict):
                segments.append(
                    {"text": s["text"], "start": s["start"], "duration": s["duration"]}
                )
            else:
                segments.append(
                    {"text": s.text, "start": s.start, "duration": s.duration}
                )
        return segments

    def _whisper_fallback(
        self,
        video_id: str,
        audio_path: str,
    ) -> dict[str, Any] | None:
        """Attempt Whisper STT transcription as fallback.

        Args:
            video_id: YouTube video ID.
            audio_path: Path to audio file.

        Returns:
            Dict with transcript data, or None if Whisper unavailable.
        """
        try:
            import importlib

            whisper = importlib.import_module("whisper")
        except (ImportError, ModuleNotFoundError):
            logger.warning(
                "Whisper not installed. Install with: pip install openai-whisper"
            )
            return None

        if whisper is None:
            logger.warning("Whisper module is None (not available)")
            return None

        try:
            model = whisper.load_model("base")
            result = model.transcribe(audio_path)
            segments = result.get("segments", [])
            return {
                "video_id": video_id,
                "transcript_type": "whisper_stt",
                "segments": [
                    {
                        "text": s["text"],
                        "start": s["start"],
                        "duration": s.get("end", s["start"]) - s["start"],
                    }
                    for s in segments
                ],
            }
        except Exception as e:
            logger.warning(
                "Whisper STT failed for %s: %s",
                video_id,
                e,
            )
            return None
