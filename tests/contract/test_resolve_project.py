"""T021 RED: contract tests for resolve_project explicit --project semantics (FR-004).

Verifies that explicit --project latest and --project <path> work the same
as before the US2 change; the producer/consumer default logic only applies
to project=None.
"""

from pathlib import Path

import pytest


def _make_committed_project(root: Path) -> Path:
    """Helper: create a project with one artifact and commit latest."""
    from tube_scout.output.manager import ProjectManager

    mgr = ProjectManager(projects_root=root)
    proj = mgr.create_project()
    collect_dir = proj / "01_collect"
    collect_dir.mkdir(parents=True, exist_ok=True)
    (collect_dir / "dummy.json").write_text("{}")
    mgr.commit_latest()
    return proj


class TestExplicitProjectLatest:
    """FR-004: --project latest resolves via symlink (unchanged)."""

    def test_latest_resolves_committed_project(self, tmp_path: Path) -> None:
        from tube_scout.cli.project import resolve_project

        proj = _make_committed_project(tmp_path)
        mgr = resolve_project(str(tmp_path), "latest", producer=False)
        assert mgr.project_dir == proj

    def test_latest_resolves_with_producer_true(self, tmp_path: Path) -> None:
        """producer=True does not affect explicit 'latest' resolution."""
        from tube_scout.cli.project import resolve_project

        proj = _make_committed_project(tmp_path)
        mgr = resolve_project(str(tmp_path), "latest", producer=True)
        assert mgr.project_dir == proj

    def test_latest_exits_when_no_symlink(self, tmp_path: Path) -> None:
        """No symlink present → typer.Exit(code=1) (legacy behavior)."""
        import typer

        from tube_scout.cli.project import resolve_project

        with pytest.raises((typer.Exit, SystemExit)):
            resolve_project(str(tmp_path), "latest", producer=False)


class TestExplicitProjectPath:
    """FR-004: --project <path> opens the exact directory (unchanged)."""

    def test_explicit_path_opens_project(self, tmp_path: Path) -> None:
        from tube_scout.cli.project import resolve_project

        proj_dir = tmp_path / "my_project"
        proj_dir.mkdir()
        mgr = resolve_project(str(tmp_path), str(proj_dir), producer=False)
        assert mgr.project_dir == proj_dir

    def test_explicit_path_nonexistent_exits(self, tmp_path: Path) -> None:
        import typer

        from tube_scout.cli.project import resolve_project

        with pytest.raises((typer.Exit, SystemExit)):
            resolve_project(str(tmp_path), str(tmp_path / "does_not_exist"), producer=False)


class TestNullProjectConsumerBehavior:
    """project=None with producer=False must open latest or raise LatestProjectMissing."""

    def test_null_consumer_opens_latest(self, tmp_path: Path) -> None:
        from tube_scout.cli.errors import LatestProjectMissing
        from tube_scout.cli.project import resolve_project

        proj = _make_committed_project(tmp_path)
        mgr = resolve_project(str(tmp_path), None, producer=False)
        assert mgr.project_dir == proj

    def test_null_consumer_raises_missing(self, tmp_path: Path) -> None:
        from tube_scout.cli.errors import LatestProjectMissing
        from tube_scout.cli.project import resolve_project

        with pytest.raises(LatestProjectMissing):
            resolve_project(str(tmp_path), None, producer=False)
