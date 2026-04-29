"""Tests for Captions API client."""

from unittest.mock import MagicMock, patch

import pytest

from tube_scout.services.captions_api import CaptionsAPIClient, CaptionTrack


class TestCaptionTrack:
    """Tests for CaptionTrack data class."""

    def test_create(self) -> None:
        track = CaptionTrack(
            caption_id="abc123",
            language="ko",
            name="Korean",
            track_kind="ASR",
        )
        assert track.caption_id == "abc123"
        assert track.language == "ko"
        assert track.track_kind == "ASR"


class TestCaptionsAPIClientListCaptions:
    """Tests for listing caption tracks."""

    def test_list_returns_tracks(self) -> None:
        mock_service = MagicMock()
        mock_service.captions().list().execute.return_value = {
            "items": [
                {
                    "id": "cap1",
                    "snippet": {
                        "language": "ko",
                        "name": "Korean (auto)",
                        "trackKind": "ASR",
                    },
                },
                {
                    "id": "cap2",
                    "snippet": {
                        "language": "en",
                        "name": "English",
                        "trackKind": "standard",
                    },
                },
            ]
        }
        client = CaptionsAPIClient(mock_service)
        tracks = client.list_captions("video123")
        assert len(tracks) == 2
        assert tracks[0].caption_id == "cap1"
        assert tracks[0].language == "ko"
        assert tracks[1].caption_id == "cap2"

    def test_list_empty_result(self) -> None:
        mock_service = MagicMock()
        mock_service.captions().list().execute.return_value = {"items": []}
        client = CaptionsAPIClient(mock_service)
        tracks = client.list_captions("video123")
        assert tracks == []

    def test_list_quota_tracking(self) -> None:
        mock_service = MagicMock()
        mock_service.captions().list().execute.return_value = {"items": []}
        client = CaptionsAPIClient(mock_service)
        assert client.quota_used == 0
        client.list_captions("video123")
        assert client.quota_used == 50  # captions.list costs 50 units


class TestCaptionsAPIClientDownload:
    """Tests for downloading caption content."""

    def test_download_srt(self) -> None:
        srt_content = (
            "1\n"
            "00:00:00,000 --> 00:00:03,000\n"
            "Hello world\n\n"
        )
        mock_service = MagicMock()
        mock_service.captions().download().execute.return_value = srt_content.encode("utf-8")
        client = CaptionsAPIClient(mock_service)
        result = client.download_caption("cap1")
        assert result == srt_content

    def test_download_quota_tracking(self) -> None:
        mock_service = MagicMock()
        mock_service.captions().download().execute.return_value = b"1\n00:00:00,000 --> 00:00:01,000\nhi\n\n"
        client = CaptionsAPIClient(mock_service)
        client.download_caption("cap1")
        assert client.quota_used == 200  # captions.download costs 200 units

    def test_download_returns_utf8_string(self) -> None:
        korean_srt = "1\n00:00:00,000 --> 00:00:03,000\n안녕하세요\n\n"
        mock_service = MagicMock()
        mock_service.captions().download().execute.return_value = korean_srt.encode("utf-8")
        client = CaptionsAPIClient(mock_service)
        result = client.download_caption("cap1")
        assert "안녕하세요" in result


class TestCaptionsAPIClientFetchSegments:
    """Tests for the high-level fetch_segments method."""

    def test_fetch_segments_prefers_korean(self) -> None:
        mock_service = MagicMock()
        mock_service.captions().list().execute.return_value = {
            "items": [
                {"id": "cap_en", "snippet": {"language": "en", "name": "English", "trackKind": "ASR"}},
                {"id": "cap_ko", "snippet": {"language": "ko", "name": "Korean", "trackKind": "ASR"}},
            ]
        }
        srt_content = (
            "1\n"
            "00:00:00,000 --> 00:00:03,000\n"
            "안녕하세요\n\n"
        )
        mock_service.captions().download().execute.return_value = srt_content.encode("utf-8")
        client = CaptionsAPIClient(mock_service)
        result = client.fetch_segments("video1")
        assert result is not None
        assert len(result) == 1
        assert result[0]["text"] == "안녕하세요"
        # Should call download with Korean track
        mock_service.captions().download.assert_called()

    def test_fetch_segments_no_tracks_returns_none(self) -> None:
        mock_service = MagicMock()
        mock_service.captions().list().execute.return_value = {"items": []}
        client = CaptionsAPIClient(mock_service)
        result = client.fetch_segments("video1")
        assert result is None

    def test_fetch_segments_total_quota(self) -> None:
        mock_service = MagicMock()
        mock_service.captions().list().execute.return_value = {
            "items": [
                {"id": "cap1", "snippet": {"language": "ko", "name": "Korean", "trackKind": "ASR"}},
            ]
        }
        mock_service.captions().download().execute.return_value = b"1\n00:00:00,000 --> 00:00:01,000\nhi\n\n"
        client = CaptionsAPIClient(mock_service)
        client.fetch_segments("video1")
        assert client.quota_used == 250  # 50 (list) + 200 (download)

    def test_quota_limit_respected(self) -> None:
        mock_service = MagicMock()
        mock_service.captions().list().execute.return_value = {
            "items": [
                {"id": "cap1", "snippet": {"language": "ko", "name": "Korean", "trackKind": "ASR"}},
            ]
        }
        mock_service.captions().download().execute.return_value = b"1\n00:00:00,000 --> 00:00:01,000\nhi\n\n"
        client = CaptionsAPIClient(mock_service, quota_limit=100)
        result = client.fetch_segments("video1")
        # list costs 50, leaving only 50 for download (needs 200), should fail gracefully
        assert result is None
        assert client.quota_used == 50  # Only list was called


class TestCaptionsAPIClientErrors:
    """Tests for error handling."""

    def test_api_error_on_list(self) -> None:
        from googleapiclient.errors import HttpError
        mock_service = MagicMock()
        mock_service.captions().list().execute.side_effect = HttpError(
            resp=MagicMock(status=403), content=b"Forbidden"
        )
        client = CaptionsAPIClient(mock_service)
        tracks = client.list_captions("video1")
        assert tracks == []

    def test_api_error_on_download(self) -> None:
        from googleapiclient.errors import HttpError
        mock_service = MagicMock()
        mock_service.captions().download().execute.side_effect = HttpError(
            resp=MagicMock(status=500), content=b"Internal error"
        )
        client = CaptionsAPIClient(mock_service)
        result = client.download_caption("cap1")
        assert result is None
