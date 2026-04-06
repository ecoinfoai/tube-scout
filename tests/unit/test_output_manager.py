"""Tests for OutputManager."""

from pathlib import Path

import pytest

from tube_scout.output.manager import OutputManager


class TestOutputManager:
    """Tests for OutputManager class."""

    def test_create_run_creates_directory(self, tmp_path: Path) -> None:
        mgr = OutputManager(base_dir=tmp_path)
        run_dir = mgr.create_run()
        assert run_dir.exists()
        assert run_dir.is_dir()

    def test_create_run_directory_name_format(self, tmp_path: Path) -> None:
        mgr = OutputManager(base_dir=tmp_path)
        run_dir = mgr.create_run()
        assert run_dir.name.startswith("report-")
        # Format: report-YYYYMMDD-HHMM
        parts = run_dir.name.split("-")
        assert len(parts) == 3
        assert len(parts[1]) == 8  # YYYYMMDD
        assert len(parts[2]) == 4  # HHMM

    def test_create_run_under_base_dir(self, tmp_path: Path) -> None:
        mgr = OutputManager(base_dir=tmp_path)
        run_dir = mgr.create_run()
        assert run_dir.parent == tmp_path

    def test_update_latest_link_creates_symlink(self, tmp_path: Path) -> None:
        mgr = OutputManager(base_dir=tmp_path)
        run_dir = mgr.create_run()
        mgr.update_latest_link(run_dir)
        latest = tmp_path / "latest"
        assert latest.is_symlink()
        assert latest.resolve() == run_dir.resolve()

    def test_update_latest_link_updates_existing(self, tmp_path: Path) -> None:
        mgr = OutputManager(base_dir=tmp_path)
        run1 = mgr.create_run()
        mgr.update_latest_link(run1)

        # Create second run directory manually
        run2 = tmp_path / "report-20260404-1300"
        run2.mkdir()
        mgr.update_latest_link(run2)

        latest = tmp_path / "latest"
        assert latest.resolve() == run2.resolve()

    def test_get_latest_returns_path(self, tmp_path: Path) -> None:
        mgr = OutputManager(base_dir=tmp_path)
        run_dir = mgr.create_run()
        mgr.update_latest_link(run_dir)
        result = mgr.get_latest()
        assert result is not None
        assert result.resolve() == run_dir.resolve()

    def test_get_latest_returns_none_when_no_symlink(self, tmp_path: Path) -> None:
        mgr = OutputManager(base_dir=tmp_path)
        result = mgr.get_latest()
        assert result is None

    def test_env_var_overrides_base_dir(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        custom_dir = tmp_path / "custom_output"
        custom_dir.mkdir()
        monkeypatch.setenv("TUBE_SCOUT_OUTPUT_DIR", str(custom_dir))
        mgr = OutputManager()
        run_dir = mgr.create_run()
        assert run_dir.parent == custom_dir

    def test_default_base_dir(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("TUBE_SCOUT_OUTPUT_DIR", raising=False)
        mgr = OutputManager()
        assert mgr.base_dir == Path("output")

    def test_create_run_creates_base_dir_if_not_exists(self, tmp_path: Path) -> None:
        base = tmp_path / "nonexistent" / "output"
        mgr = OutputManager(base_dir=base)
        run_dir = mgr.create_run()
        assert base.exists()
        assert run_dir.exists()

    def test_multiple_runs_create_separate_dirs(self, tmp_path: Path) -> None:
        mgr = OutputManager(base_dir=tmp_path)
        run1 = mgr.create_run()
        # Force a different timestamp by creating manually
        run2_path = tmp_path / "report-20260404-1301"
        run2_path.mkdir()
        assert run1 != run2_path
        assert run1.exists()
        assert run2_path.exists()
