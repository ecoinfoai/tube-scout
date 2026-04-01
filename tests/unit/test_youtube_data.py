"""Tests for YouTubeDataService."""

from unittest.mock import MagicMock

import pytest

from tube_scout.services.youtube_data import YouTubeDataService


@pytest.fixture
def mock_youtube_client() -> MagicMock:
    """Create a mock YouTube API client."""
    return MagicMock()


@pytest.fixture
def service(mock_youtube_client: MagicMock) -> YouTubeDataService:
    """Create a YouTubeDataService with mocked client."""
    return YouTubeDataService(client=mock_youtube_client)


class TestGetChannelInfo:
    """Tests for get_channel_info method."""

    def test_returns_channel_data(
        self, service: YouTubeDataService, mock_youtube_client: MagicMock
    ) -> None:
        mock_youtube_client.channels().list().execute.return_value = {
            "items": [
                {
                    "id": "UCxxxxxxxxxxxxxxxxxxxxxx",
                    "snippet": {"title": "Test Channel"},
                    "contentDetails": {
                        "relatedPlaylists": {"uploads": "UUxxxxxxxxxxxxxxxxxxxxxx"}
                    },
                    "statistics": {"videoCount": "150"},
                }
            ]
        }
        result = service.get_channel_info("UCxxxxxxxxxxxxxxxxxxxxxx")
        assert result["channel_id"] == "UCxxxxxxxxxxxxxxxxxxxxxx"
        assert result["channel_name"] == "Test Channel"
        assert result["uploads_playlist_id"] == "UUxxxxxxxxxxxxxxxxxxxxxx"

    def test_channel_not_found_raises(
        self, service: YouTubeDataService, mock_youtube_client: MagicMock
    ) -> None:
        mock_youtube_client.channels().list().execute.return_value = {"items": []}
        with pytest.raises(ValueError, match="Channel not found"):
            service.get_channel_info("UCnonexistent")


class TestListAllVideos:
    """Tests for list_all_videos method."""

    def test_single_page(
        self, service: YouTubeDataService, mock_youtube_client: MagicMock
    ) -> None:
        mock_youtube_client.playlistItems().list().execute.return_value = {
            "items": [
                {
                    "snippet": {
                        "resourceId": {"videoId": "vid1"},
                        "title": "Video 1",
                        "publishedAt": "2024-01-01T00:00:00Z",
                    }
                },
                {
                    "snippet": {
                        "resourceId": {"videoId": "vid2"},
                        "title": "Video 2",
                        "publishedAt": "2024-01-02T00:00:00Z",
                    }
                },
            ],
        }
        videos = service.list_all_videos("UUxxxxxxxxxxxxxxxxxxxxxx")
        assert len(videos) == 2
        assert videos[0]["video_id"] == "vid1"

    def test_pagination(
        self, service: YouTubeDataService, mock_youtube_client: MagicMock
    ) -> None:
        # First page has nextPageToken, second does not
        page1 = {
            "items": [
                {
                    "snippet": {
                        "resourceId": {"videoId": "vid1"},
                        "title": "Video 1",
                        "publishedAt": "2024-01-01T00:00:00Z",
                    }
                }
            ],
            "nextPageToken": "page2token",
        }
        page2 = {
            "items": [
                {
                    "snippet": {
                        "resourceId": {"videoId": "vid2"},
                        "title": "Video 2",
                        "publishedAt": "2024-01-02T00:00:00Z",
                    }
                }
            ],
        }
        mock_youtube_client.playlistItems().list().execute.side_effect = [page1, page2]
        videos = service.list_all_videos("UUxxxxxxxxxxxxxxxxxxxxxx")
        assert len(videos) == 2


class TestGetVideoDetails:
    """Tests for get_video_details method."""

    def test_batch_details(
        self, service: YouTubeDataService, mock_youtube_client: MagicMock
    ) -> None:
        mock_youtube_client.videos().list().execute.return_value = {
            "items": [
                {
                    "id": "vid1",
                    "contentDetails": {"duration": "PT10M30S"},
                    "statistics": {
                        "viewCount": "1000",
                        "likeCount": "50",
                        "commentCount": "10",
                    },
                }
            ]
        }
        details = service.get_video_details(["vid1"])
        assert details["vid1"]["duration_seconds"] == 630
        assert details["vid1"]["view_count"] == 1000
        assert details["vid1"]["like_count"] == 50


class TestFilterByProfessor:
    """Tests for filter_by_professor method."""

    def test_filters_by_name(self, service: YouTubeDataService) -> None:
        videos = [
            {"video_id": "v1", "title": "홍길동 교수 해부학"},
            {"video_id": "v2", "title": "다른 교수 생리학"},
            {"video_id": "v3", "title": "해부학 홍길동교수 특강"},
        ]
        filtered = service.filter_by_professor(videos, "홍길동")
        assert len(filtered) == 2
        assert filtered[0]["video_id"] == "v1"
        assert filtered[1]["video_id"] == "v3"

    def test_empty_result(self, service: YouTubeDataService) -> None:
        videos = [{"video_id": "v1", "title": "No match here"}]
        filtered = service.filter_by_professor(videos, "홍길동")
        assert len(filtered) == 0


class TestGetComments:
    """Tests for get_comments method (FR-005b)."""

    def test_single_page(
        self,
        service: YouTubeDataService,
        mock_youtube_client: MagicMock,
    ) -> None:
        mock_youtube_client.commentThreads().list().execute.return_value = {
            "items": [
                {
                    "snippet": {
                        "topLevelComment": {
                            "id": "c1",
                            "snippet": {
                                "authorDisplayName": "User1",
                                "textDisplay": "Great video!",
                                "publishedAt": "2024-01-01T00:00:00Z",
                                "likeCount": 3,
                            },
                        }
                    }
                },
                {
                    "snippet": {
                        "topLevelComment": {
                            "id": "c2",
                            "snippet": {
                                "authorDisplayName": "User2",
                                "textDisplay": "Helpful lecture",
                                "publishedAt": "2024-01-02T00:00:00Z",
                                "likeCount": 0,
                            },
                        }
                    }
                },
            ]
        }
        comments = service.get_comments("vid001")
        assert len(comments) == 2
        assert comments[0]["comment_id"] == "c1"
        assert comments[0]["video_id"] == "vid001"
        assert comments[0]["author"] == "User1"
        assert comments[0]["text"] == "Great video!"
        assert comments[0]["like_count"] == 3
        assert comments[1]["comment_id"] == "c2"

    def test_pagination(
        self,
        service: YouTubeDataService,
        mock_youtube_client: MagicMock,
    ) -> None:
        page1 = {
            "items": [
                {
                    "snippet": {
                        "topLevelComment": {
                            "id": "c1",
                            "snippet": {
                                "authorDisplayName": "A",
                                "textDisplay": "Page 1",
                                "publishedAt": "2024-01-01T00:00:00Z",
                                "likeCount": 0,
                            },
                        }
                    }
                },
            ],
            "nextPageToken": "token2",
        }
        page2 = {
            "items": [
                {
                    "snippet": {
                        "topLevelComment": {
                            "id": "c2",
                            "snippet": {
                                "authorDisplayName": "B",
                                "textDisplay": "Page 2",
                                "publishedAt": "2024-01-02T00:00:00Z",
                                "likeCount": 1,
                            },
                        }
                    }
                },
            ],
        }
        mock_youtube_client.commentThreads().list().execute.side_effect = [
            page1,
            page2,
        ]
        comments = service.get_comments("vid001", max_results=200)
        assert len(comments) == 2
        assert comments[0]["comment_id"] == "c1"
        assert comments[1]["comment_id"] == "c2"

    def test_empty_comments(
        self,
        service: YouTubeDataService,
        mock_youtube_client: MagicMock,
    ) -> None:
        mock_youtube_client.commentThreads().list().execute.return_value = {"items": []}
        comments = service.get_comments("vid001")
        assert comments == []
