"""Shared test fixtures for tube-scout."""

from pathlib import Path

import pytest


@pytest.fixture
def tmp_data_dir(tmp_path: Path) -> Path:
    """Create a temporary data directory structure for tests."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "raw" / "channels").mkdir(parents=True)
    (data_dir / "raw" / "comments").mkdir(parents=True)
    (data_dir / "raw" / "retention").mkdir(parents=True)
    (data_dir / "raw" / "transcripts").mkdir(parents=True)
    (data_dir / "raw" / "analytics").mkdir(parents=True)
    (data_dir / "processed" / "sentiment").mkdir(parents=True)
    (data_dir / "processed" / "segments").mkdir(parents=True)
    (data_dir / "processed" / "eqs").mkdir(parents=True)
    (data_dir / "processed" / "forecast").mkdir(parents=True)
    (data_dir / "reports" / "video").mkdir(parents=True)
    (data_dir / "reports" / "channel").mkdir(parents=True)
    (data_dir / "checkpoints").mkdir(parents=True)
    return data_dir


@pytest.fixture
def mock_api_responses_dir() -> Path:
    """Return path to mock API response fixtures directory."""
    fixtures_dir = Path(__file__).parent / "fixtures"
    fixtures_dir.mkdir(exist_ok=True)
    return fixtures_dir


@pytest.fixture
def sample_channel_id() -> str:
    """Return a sample YouTube channel ID for testing."""
    return "UCxxxxxxxxxxxxxxxxxxxxxx"


@pytest.fixture
def sample_professor_name() -> str:
    """Return a sample professor name for testing."""
    return "TestProfessor"
