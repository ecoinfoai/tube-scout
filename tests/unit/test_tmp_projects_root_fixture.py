"""Smoke test for tmp_projects_root fixture (T002)."""

import os
from pathlib import Path


def test_tmp_projects_root_yields_path(tmp_projects_root: Path) -> None:
    """Fixture yields a Path and the directory exists."""
    assert isinstance(tmp_projects_root, Path)
    assert tmp_projects_root.exists()
    assert tmp_projects_root.is_dir()


def test_tmp_projects_root_env_patched(tmp_projects_root: Path) -> None:
    """TUBE_SCOUT_PROJECTS_DIR is patched to the temp root."""
    assert os.environ.get("TUBE_SCOUT_PROJECTS_DIR") == str(tmp_projects_root)


def test_tmp_projects_root_project_manager_uses_fixture(
    tmp_projects_root: Path,
) -> None:
    """ProjectManager() without explicit root resolves to the fixture path."""
    from tube_scout.output.manager import ProjectManager

    mgr = ProjectManager()
    assert mgr._root == tmp_projects_root
