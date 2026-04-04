"""Integration tests for output isolation (US6).

Verifies that multiple pipeline runs produce separate timestamped directories,
the latest symlink points to the newest run, and --output-dir override works.
"""

import json
from pathlib import Path

import pytest

from tube_scout.output.manager import OutputManager


class TestMultipleRuns:
    """Tests for separate timestamped output directories."""

    def test_two_runs_create_separate_dirs(self, tmp_path: Path) -> None:
        mgr = OutputManager(base_dir=tmp_path)

        run1 = mgr.create_run()
        mgr.update_latest_link(run1)

        # Write data to run1
        (run1 / "parsed").mkdir(parents=True)
        (run1 / "parsed" / "parsed_titles.json").write_text(
            '["run1"]', encoding="utf-8"
        )

        # Ensure different timestamp (minute granularity)
        run2_name = "report-20260404-1300"
        run2 = tmp_path / run2_name
        run2.mkdir()
        mgr.update_latest_link(run2)

        # Write data to run2
        (run2 / "parsed").mkdir(parents=True)
        (run2 / "parsed" / "parsed_titles.json").write_text(
            '["run2"]', encoding="utf-8"
        )

        # Both directories exist independently
        assert run1.exists()
        assert run2.exists()
        assert run1 != run2

        # run1 data is untouched
        data1 = json.loads(
            (run1 / "parsed" / "parsed_titles.json").read_text(encoding="utf-8")
        )
        assert data1 == ["run1"]

        # run2 data is independent
        data2 = json.loads(
            (run2 / "parsed" / "parsed_titles.json").read_text(encoding="utf-8")
        )
        assert data2 == ["run2"]

    def test_previous_run_not_modified(self, tmp_path: Path) -> None:
        mgr = OutputManager(base_dir=tmp_path)
        run1 = mgr.create_run()
        mgr.update_latest_link(run1)

        # Write sentinel file
        sentinel = run1 / "sentinel.txt"
        sentinel.write_text("original", encoding="utf-8")

        # Create second run
        run2_path = tmp_path / "report-20260404-1400"
        run2_path.mkdir()
        mgr.update_latest_link(run2_path)

        # Original sentinel unchanged
        assert sentinel.read_text(encoding="utf-8") == "original"


class TestLatestSymlink:
    """Tests for latest symlink behavior."""

    def test_latest_points_to_newest_run(self, tmp_path: Path) -> None:
        mgr = OutputManager(base_dir=tmp_path)

        run1 = mgr.create_run()
        mgr.update_latest_link(run1)
        assert mgr.get_latest() == run1.resolve()

        run2 = tmp_path / "report-20260404-1500"
        run2.mkdir()
        mgr.update_latest_link(run2)
        assert mgr.get_latest() == run2.resolve()

    def test_latest_symlink_is_symlink(self, tmp_path: Path) -> None:
        mgr = OutputManager(base_dir=tmp_path)
        run_dir = mgr.create_run()
        mgr.update_latest_link(run_dir)
        latest = tmp_path / "latest"
        assert latest.is_symlink()

    def test_get_latest_none_when_no_runs(self, tmp_path: Path) -> None:
        mgr = OutputManager(base_dir=tmp_path)
        assert mgr.get_latest() is None


class TestOutputDirOverride:
    """Tests for --output-dir override."""

    def test_custom_base_dir(self, tmp_path: Path) -> None:
        custom = tmp_path / "custom_output"
        custom.mkdir()
        mgr = OutputManager(base_dir=custom)
        run_dir = mgr.create_run()
        assert run_dir.parent == custom

    def test_env_var_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        env_dir = tmp_path / "env_output"
        env_dir.mkdir()
        monkeypatch.setenv("TUBE_SCOUT_OUTPUT_DIR", str(env_dir))
        mgr = OutputManager()
        run_dir = mgr.create_run()
        assert run_dir.parent == env_dir

    def test_explicit_base_dir_overrides_env(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        env_dir = tmp_path / "env_output"
        env_dir.mkdir()
        explicit_dir = tmp_path / "explicit_output"
        explicit_dir.mkdir()
        monkeypatch.setenv("TUBE_SCOUT_OUTPUT_DIR", str(env_dir))
        mgr = OutputManager(base_dir=explicit_dir)
        run_dir = mgr.create_run()
        assert run_dir.parent == explicit_dir


class TestOutputStructure:
    """Tests for expected output directory structure."""

    def test_run_dir_follows_naming_convention(self, tmp_path: Path) -> None:
        mgr = OutputManager(base_dir=tmp_path)
        run_dir = mgr.create_run()
        name = run_dir.name
        assert name.startswith("report-")
        parts = name.split("-")
        assert len(parts) == 3
        assert len(parts[1]) == 8  # YYYYMMDD
        assert len(parts[2]) == 4  # HHMM

    def test_subdirectories_can_be_created(self, tmp_path: Path) -> None:
        mgr = OutputManager(base_dir=tmp_path)
        run_dir = mgr.create_run()

        # Create expected subdirectories
        (run_dir / "raw" / "channels" / "UCtest").mkdir(parents=True)
        (run_dir / "parsed" / "UCtest").mkdir(parents=True)
        (run_dir / "validation" / "UCtest").mkdir(parents=True)
        (run_dir / "reports" / "department").mkdir(parents=True)

        assert (run_dir / "raw" / "channels" / "UCtest").is_dir()
        assert (run_dir / "parsed" / "UCtest").is_dir()
        assert (run_dir / "validation" / "UCtest").is_dir()
        assert (run_dir / "reports" / "department").is_dir()
