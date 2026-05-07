"""Tests for CLI project resolver."""

from pathlib import Path

import click.exceptions
import pytest

from tube_scout.cli.project import resolve_project
from tube_scout.output.manager import ProjectManager


class TestResolveProject:
    """Tests for resolve_project helper."""

    def test_none_with_producer_creates_new_project(self, tmp_path: Path) -> None:
        # Spec 009 T026: project=None requires producer=True to create a new
        # project; consumer mode (default) raises LatestProjectMissing.
        mgr = resolve_project(
            str(tmp_path / "projects"), project=None, producer=True
        )
        assert isinstance(mgr, ProjectManager)
        assert mgr.project_dir.exists()

    def test_none_consumer_raises_latest_missing(self, tmp_path: Path) -> None:
        # Spec 009 T026: consumer mode + no latest project → LatestProjectMissing.
        from tube_scout.cli.errors import LatestProjectMissing

        with pytest.raises(LatestProjectMissing):
            resolve_project(str(tmp_path / "projects"), project=None)

    def test_latest_resolves_symlink(self, tmp_path: Path) -> None:
        root = tmp_path / "projects"
        first = ProjectManager(projects_root=root)
        first.create_project()
        # idea6 ADR-IDEA6-006: must commit_latest after writing an artifact.
        first.videos_meta("nursing").write_text("[]", encoding="utf-8")
        first.commit_latest()

        mgr = resolve_project(str(root), project="latest")
        assert mgr.project_dir == first.project_dir

    def test_latest_raises_when_no_link(self, tmp_path: Path) -> None:
        root = tmp_path / "projects"
        root.mkdir(parents=True)
        with pytest.raises((SystemExit, click.exceptions.Exit)):
            resolve_project(str(root), project="latest")

    def test_explicit_path_opens_project(self, tmp_path: Path) -> None:
        root = tmp_path / "projects"
        project_dir = root / "20260404-120000"
        project_dir.mkdir(parents=True)

        mgr = resolve_project(str(root), project=str(project_dir))
        assert mgr.project_dir == project_dir

    def test_explicit_path_raises_on_missing(self, tmp_path: Path) -> None:
        root = tmp_path / "projects"
        with pytest.raises((SystemExit, click.exceptions.Exit)):
            resolve_project(str(root), project=str(root / "nonexistent"))
