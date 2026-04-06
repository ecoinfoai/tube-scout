"""Integration tests for the collect videos flow."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from tube_scout.cli.main import app
from tube_scout.storage.json_store import read_json, write_json
from tube_scout.storage.parquet_store import read_parquet

runner = CliRunner()


def _setup_config(data_dir: Path) -> None:
    """Write a valid config.json to data_dir."""
    config = {
        "channels": [
            {
                "channel_id": "UCxxxxxxxxxxxxxxxxxxxxxx",
                "professor_name": "TestProfessor",
            }
        ],
        "settings": {
            "data_dir": str(data_dir),
            "sentiment_backend": "llm",
            "default_report_format": "html",
        },
    }
    write_json(data_dir / "config.json", config)


def _mock_channel_response() -> dict:
    return {
        "items": [
            {
                "id": "UCxxxxxxxxxxxxxxxxxxxxxx",
                "snippet": {"title": "Test Channel"},
                "contentDetails": {
                    "relatedPlaylists": {"uploads": "UUxxxxxxxxxxxxxxxxxxxxxx"}
                },
                "statistics": {"videoCount": "2"},
            }
        ]
    }


def _mock_playlist_response() -> dict:
    return {
        "items": [
            {
                "snippet": {
                    "resourceId": {"videoId": "vid001"},
                    "title": "TestProfessor Lecture 1",
                    "publishedAt": "2024-01-01T00:00:00Z",
                }
            },
            {
                "snippet": {
                    "resourceId": {"videoId": "vid002"},
                    "title": "TestProfessor Lecture 2",
                    "publishedAt": "2024-01-15T00:00:00Z",
                }
            },
            {
                "snippet": {
                    "resourceId": {"videoId": "vid003"},
                    "title": "Other Video No Match",
                    "publishedAt": "2024-02-01T00:00:00Z",
                }
            },
        ]
    }


def _mock_video_details_response() -> dict:
    return {
        "items": [
            {
                "id": "vid001",
                "contentDetails": {"duration": "PT15M0S"},
                "statistics": {
                    "viewCount": "500",
                    "likeCount": "25",
                    "commentCount": "5",
                },
            },
            {
                "id": "vid002",
                "contentDetails": {"duration": "PT30M0S"},
                "statistics": {
                    "viewCount": "1200",
                    "likeCount": "60",
                    "commentCount": "15",
                },
            },
        ]
    }


class TestCollectVideosFlow:
    """Integration test: init -> collect videos -> verify data files."""

    @patch("tube_scout.services.auth.build_data_client")
    def test_collect_creates_data_files(
        self, mock_build_client: MagicMock, tmp_path: Path
    ) -> None:
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "checkpoints").mkdir(parents=True)
        _setup_config(data_dir)

        # Set up mock API client
        mock_client = MagicMock()
        mock_build_client.return_value = mock_client

        mock_client.channels().list.return_value.execute.return_value = (
            _mock_channel_response()
        )
        mock_client.playlistItems().list.return_value.execute.return_value = (
            _mock_playlist_response()
        )
        mock_client.videos().list.return_value.execute.return_value = (
            _mock_video_details_response()
        )

        project_dir = tmp_path / "projects"
        result = runner.invoke(
            app,
            [
                "collect",
                "videos",
                "--data-dir",
                str(data_dir),
                "--project-dir",
                str(project_dir),
            ],
        )
        assert result.exit_code == 0

        # Find the created project directory
        latest = project_dir / "latest"
        assert latest.is_symlink()
        proj = latest.resolve()

        # Verify data files were created under 01_collect
        channel_dir = proj / "01_collect" / "channels" / "UCxxxxxxxxxxxxxxxxxxxxxx"
        assert channel_dir.exists()

        videos_meta = read_json(channel_dir / "videos_meta.json")
        assert videos_meta is not None
        # Should only contain professor-filtered videos (2 out of 3)
        videos = (
            videos_meta
            if isinstance(videos_meta, list)
            else videos_meta.get("videos", [])
        )
        assert len(videos) == 2

        # T024: Parquet file should also be created
        parquet_path = channel_dir / "videos_meta.parquet"
        assert parquet_path.exists()
        df = read_parquet(parquet_path)
        assert df is not None
        assert len(df) == 2
        assert "video_id" in df.columns
