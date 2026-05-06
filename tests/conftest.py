"""Shared test fixtures for tube-scout."""

from pathlib import Path
from typing import Generator

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    """Add ``--run-manual`` opt-in for tests/manual/* (FR-IDEA6-009)."""
    parser.addoption(
        "--run-manual",
        action="store_true",
        default=False,
        help="Collect tests/manual/* (require live OAuth credentials).",
    )


def pytest_collection_modifyitems(  # type: ignore[no-untyped-def]
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    """Skip tests under ``tests/manual/`` unless ``--run-manual`` is set."""
    if config.getoption("--run-manual"):
        return
    skip_manual = pytest.mark.skip(reason="needs --run-manual (FR-IDEA6-009)")
    for item in items:
        if "tests/manual" in str(item.fspath):
            item.add_marker(skip_manual)


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
def tmp_projects_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Generator[Path, None, None]:
    """Yield a temporary projects root directory and patch env + CWD defaults.

    Patches TUBE_SCOUT_PROJECTS_DIR so that any ProjectManager constructed
    without an explicit ``projects_root`` argument uses this temp directory
    instead of a relative ``./projects`` that would pollute the working tree.
    """
    root = tmp_path / "projects"
    root.mkdir()
    monkeypatch.setenv("TUBE_SCOUT_PROJECTS_DIR", str(root))
    yield root


@pytest.fixture
def tmp_project(tmp_path: Path):  # type: ignore[no-untyped-def]
    """Create a temporary project with ProjectManager."""
    from tube_scout.output.manager import ProjectManager

    mgr = ProjectManager(projects_root=tmp_path / "projects")
    mgr.create_project()
    return mgr


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
