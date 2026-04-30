"""Tests for ProjectManager."""

from pathlib import Path

import pytest

from tube_scout.output.manager import ProjectManager


class TestProjectManagerCreate:
    """Tests for creating new projects."""

    def test_create_project_creates_timestamped_dir(self, tmp_path: Path) -> None:
        mgr = ProjectManager(projects_root=tmp_path / "projects")
        project_dir = mgr.create_project()
        assert project_dir.exists()
        assert project_dir.parent == tmp_path / "projects"

    def test_create_project_does_not_update_latest_symlink(self, tmp_path: Path) -> None:
        """idea6 ADR-IDEA6-006 (D-3 fix): create_project no longer touches latest.

        Writers must call commit_latest() after persisting at least one
        artifact. This test pins the new contract.
        """
        mgr = ProjectManager(projects_root=tmp_path / "projects")
        mgr.create_project()
        latest = tmp_path / "projects" / "latest"
        assert not latest.is_symlink(), (
            "create_project must not auto-update latest (ADR-IDEA6-006)"
        )

    def test_create_project_dir_name_is_timestamp(self, tmp_path: Path) -> None:
        mgr = ProjectManager(projects_root=tmp_path / "projects")
        project_dir = mgr.create_project()
        # Format: YYYYMMDD-HHMMSS
        name = project_dir.name
        assert len(name) == 15
        assert name[8] == "-"


class TestProjectManagerOpen:
    """Tests for opening existing projects."""

    def test_open_project_succeeds(self, tmp_path: Path) -> None:
        project_dir = tmp_path / "projects" / "20260404-120000"
        project_dir.mkdir(parents=True)
        mgr = ProjectManager(projects_root=tmp_path / "projects")
        mgr.open_project(project_dir)
        assert mgr.project_dir == project_dir

    def test_open_project_raises_on_missing(self, tmp_path: Path) -> None:
        mgr = ProjectManager(projects_root=tmp_path / "projects")
        with pytest.raises(FileNotFoundError):
            mgr.open_project(tmp_path / "nonexistent")


class TestProjectManagerStepDirs:
    """Tests for step directory properties."""

    def test_collect_dir_creates_subdirectory(self, tmp_path: Path) -> None:
        mgr = ProjectManager(projects_root=tmp_path / "projects")
        mgr.create_project()
        collect = mgr.collect_dir
        assert collect.exists()
        assert collect.name == "01_collect"

    def test_analyze_dir_creates_subdirectory(self, tmp_path: Path) -> None:
        mgr = ProjectManager(projects_root=tmp_path / "projects")
        mgr.create_project()
        analyze = mgr.analyze_dir
        assert analyze.exists()
        assert analyze.name == "02_analyze"

    def test_report_dir_creates_subdirectory(self, tmp_path: Path) -> None:
        mgr = ProjectManager(projects_root=tmp_path / "projects")
        mgr.create_project()
        report = mgr.report_dir
        assert report.exists()
        assert report.name == "03_report"

    def test_checkpoint_dir_creates_subdirectory(self, tmp_path: Path) -> None:
        mgr = ProjectManager(projects_root=tmp_path / "projects")
        mgr.create_project()
        ckpt = mgr.checkpoint_dir
        assert ckpt.exists()
        assert ckpt.name == "checkpoints"

    def test_step_dirs_are_under_project(self, tmp_path: Path) -> None:
        mgr = ProjectManager(projects_root=tmp_path / "projects")
        project_dir = mgr.create_project()
        assert mgr.collect_dir.parent == project_dir
        assert mgr.analyze_dir.parent == project_dir
        assert mgr.report_dir.parent == project_dir


class TestProjectManagerLatest:
    """Tests for latest symlink resolution."""

    def test_resolve_latest_returns_none_when_no_link(self, tmp_path: Path) -> None:
        mgr = ProjectManager(projects_root=tmp_path / "projects")
        assert mgr.resolve_latest() is None

    def test_resolve_latest_returns_path_after_commit(
        self, tmp_path: Path
    ) -> None:
        """idea6 ADR-IDEA6-006: latest only resolved after commit_latest()."""
        mgr = ProjectManager(projects_root=tmp_path / "projects")
        project_dir = mgr.create_project()
        # Populate 01_collect/ with at least one artifact (B2 guard).
        mgr.videos_meta("nursing").write_text("[]", encoding="utf-8")
        mgr.commit_latest()
        latest = mgr.resolve_latest()
        assert latest is not None
        assert latest.resolve() == project_dir.resolve()

    def test_project_dir_raises_before_create(self, tmp_path: Path) -> None:
        mgr = ProjectManager(projects_root=tmp_path / "projects")
        with pytest.raises(RuntimeError):
            _ = mgr.project_dir
