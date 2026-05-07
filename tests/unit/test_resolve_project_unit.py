"""T020 RED: unit tests for resolve_project producer/consumer semantics (US2).

Tests for:
- resolve_project(project_dir, project=None, producer=False) -> opens latest
- resolve_project(project_dir, project=None, producer=False) -> raises LatestProjectMissing
- resolve_project(project_dir, project=None, producer=True) -> creates new project
"""

from pathlib import Path

import pytest

from tube_scout.cli.errors import LatestProjectMissing


def test_consumer_opens_existing_latest(tmp_path: Path) -> None:
    """Consumer (producer=False) opens the committed latest project."""
    from tube_scout.cli.project import resolve_project
    from tube_scout.output.manager import ProjectManager

    # Arrange: create a real project and commit latest
    mgr_setup = ProjectManager(projects_root=tmp_path)
    proj = mgr_setup.create_project()
    # Write an artifact so commit_latest won't refuse
    collect_dir = proj / "01_collect"
    collect_dir.mkdir(parents=True, exist_ok=True)
    (collect_dir / "dummy.json").write_text("{}")
    mgr_setup.commit_latest()

    # Act
    mgr = resolve_project(str(tmp_path), None, producer=False)

    # Assert: opened same project
    assert mgr.project_dir == proj


def test_consumer_raises_when_no_latest(tmp_path: Path) -> None:
    """Consumer (producer=False) raises LatestProjectMissing when no latest exists."""
    from tube_scout.cli.project import resolve_project

    with pytest.raises(LatestProjectMissing):
        resolve_project(str(tmp_path), None, producer=False)


def test_producer_creates_new_project(tmp_path: Path) -> None:
    """Producer (producer=True) creates a fresh project regardless of latest state."""
    from tube_scout.cli.project import resolve_project

    mgr = resolve_project(str(tmp_path), None, producer=True)

    assert mgr.project_dir.exists()
    assert mgr.project_dir.parent == tmp_path


def test_producer_creates_new_even_when_latest_exists(tmp_path: Path) -> None:
    """Producer always creates a new project even if latest already points somewhere."""
    import time

    from tube_scout.cli.project import resolve_project
    from tube_scout.output.manager import ProjectManager

    mgr_setup = ProjectManager(projects_root=tmp_path)
    first = mgr_setup.create_project()
    collect_dir = first / "01_collect"
    collect_dir.mkdir(parents=True, exist_ok=True)
    (collect_dir / "dummy.json").write_text("{}")
    mgr_setup.commit_latest()

    # Wait 1s so the timestamp-based project name differs
    time.sleep(1)
    mgr = resolve_project(str(tmp_path), None, producer=True)

    assert mgr.project_dir != first
    assert mgr.project_dir.exists()
