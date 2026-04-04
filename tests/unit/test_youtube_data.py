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


class TestYouTubeDataServiceInit:
    """Tests for YouTubeDataService OAuth-only constructor (US1)."""

    def test_requires_client_param(self) -> None:
        """YouTubeDataService must be created with a client parameter."""
        client = MagicMock()
        svc = YouTubeDataService(client=client)
        assert svc._client is client

    def test_raises_without_client(self) -> None:
        """YouTubeDataService must raise TypeError when no client provided."""
        with pytest.raises(TypeError):
            YouTubeDataService()

    def test_raises_when_api_key_passed(self) -> None:
        """YouTubeDataService must reject api_key parameter (removed)."""
        with pytest.raises(TypeError):
            YouTubeDataService(api_key="fake-key")


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


class TestGetVideoDetailsExtended:
    """Tests for extended video metadata (T031 - US2)."""

    def test_extended_fields_from_snippet(
        self, service: YouTubeDataService, mock_youtube_client: MagicMock
    ) -> None:
        mock_youtube_client.videos().list().execute.return_value = {
            "items": [
                {
                    "id": "vid1",
                    "snippet": {
                        "description": "Anatomy lecture week 1",
                        "tags": ["anatomy", "lecture"],
                        "categoryId": "27",
                        "thumbnails": {
                            "default": {"url": "https://i.ytimg.com/vi/vid1/default.jpg"}
                        },
                        "defaultLanguage": "ko",
                    },
                    "contentDetails": {
                        "duration": "PT45M",
                        "caption": "true",
                    },
                    "statistics": {
                        "viewCount": "500",
                        "likeCount": "20",
                        "commentCount": "5",
                    },
                    "status": {
                        "privacyStatus": "unlisted",
                    },
                    "topicDetails": {
                        "topicCategories": [
                            "https://en.wikipedia.org/wiki/Health",
                            "https://en.wikipedia.org/wiki/Education",
                        ]
                    },
                }
            ]
        }
        details = service.get_video_details(["vid1"])
        d = details["vid1"]
        assert d["description"] == "Anatomy lecture week 1"
        assert d["tags"] == ["anatomy", "lecture"]
        assert d["category_id"] == "27"
        assert d["thumbnail_url"] == "https://i.ytimg.com/vi/vid1/default.jpg"
        assert d["default_language"] == "ko"
        assert d["privacy_status"] == "unlisted"
        assert d["has_captions"] is True
        assert "https://en.wikipedia.org/wiki/Health" in d["topic_categories"]
        assert "https://en.wikipedia.org/wiki/Education" in d["topic_categories"]
        # Original fields still present
        assert d["duration_seconds"] == 2700
        assert d["view_count"] == 500

    def test_missing_optional_fields_default_gracefully(
        self, service: YouTubeDataService, mock_youtube_client: MagicMock
    ) -> None:
        mock_youtube_client.videos().list().execute.return_value = {
            "items": [
                {
                    "id": "vid2",
                    "snippet": {},
                    "contentDetails": {"duration": "PT5M"},
                    "statistics": {"viewCount": "10"},
                    "status": {},
                }
            ]
        }
        details = service.get_video_details(["vid2"])
        d = details["vid2"]
        assert d["description"] is None
        assert d["tags"] == []
        assert d["category_id"] is None
        assert d["thumbnail_url"] is None
        assert d["default_language"] is None
        assert d["privacy_status"] == "unknown"
        assert d["topic_categories"] == []
        assert d["has_captions"] is False

    def test_api_parts_include_extended(
        self, service: YouTubeDataService, mock_youtube_client: MagicMock
    ) -> None:
        mock_youtube_client.videos().list().execute.return_value = {"items": []}
        service.get_video_details(["vid1"])
        call_kwargs = mock_youtube_client.videos().list.call_args
        parts = call_kwargs.kwargs.get("part", "") if call_kwargs.kwargs else ""
        # Should request snippet, status, topicDetails in addition to original parts
        required = [
            "snippet", "contentDetails", "statistics",
            "status", "topicDetails",
        ]
        for required_part in required:
            assert required_part in parts


class TestGetChannelInfoExtended:
    """Tests for extended channel info (T035 - US2)."""

    def test_returns_extended_channel_data(
        self, service: YouTubeDataService, mock_youtube_client: MagicMock
    ) -> None:
        mock_youtube_client.channels().list().execute.return_value = {
            "items": [
                {
                    "id": "UCxxxxxxxxxxxxxxxxxxxxxx",
                    "snippet": {
                        "title": "Test Channel",
                        "description": "A channel about anatomy",
                    },
                    "contentDetails": {
                        "relatedPlaylists": {"uploads": "UUxxxxxxxxxxxxxxxxxxxxxx"}
                    },
                    "statistics": {
                        "videoCount": "150",
                        "subscriberCount": "5000",
                        "viewCount": "1000000",
                    },
                }
            ]
        }
        result = service.get_channel_info("UCxxxxxxxxxxxxxxxxxxxxxx")
        assert result["subscriber_count"] == 5000
        assert result["total_view_count"] == 1000000
        assert result["description"] == "A channel about anatomy"

    def test_missing_extended_fields_default_gracefully(
        self, service: YouTubeDataService, mock_youtube_client: MagicMock
    ) -> None:
        mock_youtube_client.channels().list().execute.return_value = {
            "items": [
                {
                    "id": "UCxxxxxxxxxxxxxxxxxxxxxx",
                    "snippet": {"title": "Minimal Channel"},
                    "contentDetails": {
                        "relatedPlaylists": {"uploads": "UUxxxxxxxxxxxxxxxxxxxxxx"}
                    },
                    "statistics": {"videoCount": "0"},
                }
            ]
        }
        result = service.get_channel_info("UCxxxxxxxxxxxxxxxxxxxxxx")
        assert result["subscriber_count"] == 0
        assert result["total_view_count"] == 0
        assert result["description"] is None


class TestGetCommentReplies:
    """Tests for comment reply collection (T032 - US2)."""

    def test_get_replies_for_thread(
        self, service: YouTubeDataService, mock_youtube_client: MagicMock
    ) -> None:
        mock_youtube_client.comments().list().execute.return_value = {
            "items": [
                {
                    "id": "reply1",
                    "snippet": {
                        "parentId": "c1",
                        "authorDisplayName": "Replier1",
                        "textDisplay": "Thanks for the answer!",
                        "publishedAt": "2024-01-03T00:00:00Z",
                        "likeCount": 1,
                    },
                },
                {
                    "id": "reply2",
                    "snippet": {
                        "parentId": "c1",
                        "authorDisplayName": "Replier2",
                        "textDisplay": "I agree",
                        "publishedAt": "2024-01-04T00:00:00Z",
                        "likeCount": 0,
                    },
                },
            ]
        }
        replies = service.get_comment_replies("c1", "vid001")
        assert len(replies) == 2
        assert replies[0]["comment_id"] == "reply1"
        assert replies[0]["parent_comment_id"] == "c1"
        assert replies[0]["video_id"] == "vid001"
        assert replies[0]["text"] == "Thanks for the answer!"
        assert replies[1]["comment_id"] == "reply2"

    def test_get_replies_empty(
        self, service: YouTubeDataService, mock_youtube_client: MagicMock
    ) -> None:
        mock_youtube_client.comments().list().execute.return_value = {"items": []}
        replies = service.get_comment_replies("c1", "vid001")
        assert replies == []

    def test_get_replies_pagination(
        self, service: YouTubeDataService, mock_youtube_client: MagicMock
    ) -> None:
        page1 = {
            "items": [
                {
                    "id": "r1",
                    "snippet": {
                        "parentId": "c1",
                        "authorDisplayName": "A",
                        "textDisplay": "Reply 1",
                        "publishedAt": "2024-01-01T00:00:00Z",
                        "likeCount": 0,
                    },
                },
            ],
            "nextPageToken": "next",
        }
        page2 = {
            "items": [
                {
                    "id": "r2",
                    "snippet": {
                        "parentId": "c1",
                        "authorDisplayName": "B",
                        "textDisplay": "Reply 2",
                        "publishedAt": "2024-01-02T00:00:00Z",
                        "likeCount": 0,
                    },
                },
            ],
        }
        mock_youtube_client.comments().list().execute.side_effect = [page1, page2]
        replies = service.get_comment_replies("c1", "vid001")
        assert len(replies) == 2

    def test_get_comments_includes_reply_count(
        self, service: YouTubeDataService, mock_youtube_client: MagicMock
    ) -> None:
        mock_youtube_client.commentThreads().list().execute.return_value = {
            "items": [
                {
                    "snippet": {
                        "totalReplyCount": 3,
                        "topLevelComment": {
                            "id": "c1",
                            "snippet": {
                                "authorDisplayName": "User1",
                                "textDisplay": "Question?",
                                "publishedAt": "2024-01-01T00:00:00Z",
                                "likeCount": 0,
                            },
                        },
                    }
                },
            ]
        }
        comments = service.get_comments("vid001")
        assert comments[0]["reply_count"] == 3
        assert comments[0]["parent_comment_id"] is None

    def test_get_comments_with_replies(
        self, service: YouTubeDataService, mock_youtube_client: MagicMock
    ) -> None:
        mock_youtube_client.commentThreads().list().execute.return_value = {
            "items": [
                {
                    "snippet": {
                        "totalReplyCount": 1,
                        "topLevelComment": {
                            "id": "c1",
                            "snippet": {
                                "authorDisplayName": "User1",
                                "textDisplay": "Question?",
                                "publishedAt": "2024-01-01T00:00:00Z",
                                "likeCount": 0,
                            },
                        },
                    }
                },
            ]
        }
        mock_youtube_client.comments().list().execute.return_value = {
            "items": [
                {
                    "id": "r1",
                    "snippet": {
                        "parentId": "c1",
                        "authorDisplayName": "Replier",
                        "textDisplay": "Answer!",
                        "publishedAt": "2024-01-02T00:00:00Z",
                        "likeCount": 0,
                    },
                },
            ]
        }
        comments = service.get_comments("vid001", include_replies=True)
        assert len(comments) == 2
        top_level = [c for c in comments if c["parent_comment_id"] is None]
        replies = [c for c in comments if c["parent_comment_id"] is not None]
        assert len(top_level) == 1
        assert len(replies) == 1
        assert replies[0]["parent_comment_id"] == "c1"


class TestDetectNewVideos:
    """Tests for new video detection (T033 - US2)."""

    def test_detect_new_videos(
        self, service: YouTubeDataService
    ) -> None:
        api_videos = [
            {"video_id": "vid1", "title": "V1", "published_at": "2024-01-01T00:00:00Z"},
            {"video_id": "vid2", "title": "V2", "published_at": "2024-01-02T00:00:00Z"},
            {"video_id": "vid3", "title": "V3", "published_at": "2024-01-03T00:00:00Z"},
        ]
        existing_ids = {"vid1", "vid2"}
        new_videos = service.detect_new_videos(api_videos, existing_ids)
        assert len(new_videos) == 1
        assert new_videos[0]["video_id"] == "vid3"

    def test_detect_no_new_videos(
        self, service: YouTubeDataService
    ) -> None:
        api_videos = [
            {"video_id": "vid1", "title": "V1", "published_at": "2024-01-01T00:00:00Z"},
        ]
        existing_ids = {"vid1"}
        new_videos = service.detect_new_videos(api_videos, existing_ids)
        assert new_videos == []

    def test_detect_all_new_when_empty_existing(
        self, service: YouTubeDataService
    ) -> None:
        api_videos = [
            {"video_id": "vid1", "title": "V1", "published_at": "2024-01-01T00:00:00Z"},
            {"video_id": "vid2", "title": "V2", "published_at": "2024-01-02T00:00:00Z"},
        ]
        new_videos = service.detect_new_videos(api_videos, set())
        assert len(new_videos) == 2


class TestHandleDeletedPrivateVideos:
    """Tests for 404/403 handling on deleted/private videos (T039a - US2)."""

    def test_get_video_details_skips_missing_videos(
        self, service: YouTubeDataService, mock_youtube_client: MagicMock
    ) -> None:
        """Videos that are deleted/private won't appear in API response items."""
        mock_youtube_client.videos().list().execute.return_value = {
            "items": [
                {
                    "id": "vid1",
                    "snippet": {"description": "Exists"},
                    "contentDetails": {"duration": "PT10M"},
                    "statistics": {"viewCount": "100"},
                    "status": {"privacyStatus": "public"},
                }
            ]
        }
        # Request vid1 and vid_deleted, only vid1 returned
        details = service.get_video_details(["vid1", "vid_deleted"])
        assert "vid1" in details
        assert "vid_deleted" not in details

    def test_get_comments_handles_disabled_comments(
        self, service: YouTubeDataService, mock_youtube_client: MagicMock
    ) -> None:
        from googleapiclient.errors import HttpError

        resp = MagicMock()
        resp.status = 403
        mock_youtube_client.commentThreads().list().execute.side_effect = HttpError(
            resp, b'{"error": {"code": 403, "message": "Comments are disabled"}}'
        )
        comments = service.get_comments("vid_no_comments")
        assert comments == []

    def test_get_comments_raises_on_other_errors(
        self, service: YouTubeDataService, mock_youtube_client: MagicMock
    ) -> None:
        from googleapiclient.errors import HttpError

        resp = MagicMock()
        resp.status = 500
        mock_youtube_client.commentThreads().list().execute.side_effect = HttpError(
            resp, b'{"error": {"code": 500, "message": "Server error"}}'
        )
        with pytest.raises(HttpError):
            service.get_comments("vid_server_error")
