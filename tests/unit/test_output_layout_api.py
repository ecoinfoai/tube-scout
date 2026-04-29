"""RED test for OutputLayout/ProjectManager alias-aware API.

Spec: idea6 / FR-IDEA6-001 / ADR-IDEA6-001 / T-IDEA6-A1.

Asserts the new alias-aware API surface that ProjectManager MUST expose:
- ``Stage`` StrEnum (01_collect, 02_analyze, 03_report, checkpoints).
- ``stage_dir(stage, alias) -> Path``.
- ``videos_meta(alias) -> Path`` returning the canonical
  ``projects/{ts}/01_collect/{alias}/videos_meta.json`` path.
- ``parsed_titles(alias) -> Path``.
- ``fingerprints(alias) -> Path``.
- ``report_html(alias) -> Path``.

The current ``ProjectManager`` exposes step-named class attributes and
properties that do not take an alias. These tests fail until T-IDEA6-A2
GREEN lands the new API.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tube_scout.output.manager import ProjectManager


class TestStageEnum:
    """The ``Stage`` StrEnum exists and exposes the four canonical stages."""

    def test_stage_enum_imports(self) -> None:
        from tube_scout.output.manager import Stage

        assert Stage.COLLECT.value == "01_collect"
        assert Stage.ANALYZE.value == "02_analyze"
        assert Stage.REPORT.value == "03_report"
        assert Stage.CHECKPOINTS.value == "checkpoints"

    def test_stage_enum_is_str(self) -> None:
        from tube_scout.output.manager import Stage

        assert isinstance(Stage.COLLECT.value, str)
        assert str(Stage.COLLECT) == "Stage.COLLECT" or Stage.COLLECT == "01_collect"


class TestStageDir:
    """``stage_dir(stage, alias)`` returns ``{project}/{stage}/{alias}/``."""

    def test_stage_dir_collect(self, tmp_path: Path) -> None:
        from tube_scout.output.manager import Stage

        mgr = ProjectManager(projects_root=tmp_path)
        mgr.create_project()

        result = mgr.stage_dir(Stage.COLLECT, "nursing")
        assert result.exists()
        assert result.is_dir()
        assert result.parent.name == "01_collect"
        assert result.name == "nursing"

    def test_stage_dir_analyze(self, tmp_path: Path) -> None:
        from tube_scout.output.manager import Stage

        mgr = ProjectManager(projects_root=tmp_path)
        mgr.create_project()

        result = mgr.stage_dir(Stage.ANALYZE, "nursing")
        assert result.parent.name == "02_analyze"
        assert result.name == "nursing"

    def test_stage_dir_report(self, tmp_path: Path) -> None:
        from tube_scout.output.manager import Stage

        mgr = ProjectManager(projects_root=tmp_path)
        mgr.create_project()

        result = mgr.stage_dir(Stage.REPORT, "nursing")
        assert result.parent.name == "03_report"
        assert result.name == "nursing"

    def test_stage_dir_idempotent(self, tmp_path: Path) -> None:
        """Calling stage_dir twice with the same args returns the same path."""
        from tube_scout.output.manager import Stage

        mgr = ProjectManager(projects_root=tmp_path)
        mgr.create_project()

        first = mgr.stage_dir(Stage.COLLECT, "nursing")
        second = mgr.stage_dir(Stage.COLLECT, "nursing")
        assert first == second
        assert first.exists()


class TestArtifactPaths:
    """The four canonical artifact accessors yield alias-partitioned paths."""

    def test_videos_meta_path(self, tmp_path: Path) -> None:
        mgr = ProjectManager(projects_root=tmp_path)
        mgr.create_project()

        path = mgr.videos_meta("nursing")
        assert path.name == "videos_meta.json"
        assert path.parent.name == "nursing"
        assert path.parent.parent.name == "01_collect"

    def test_parsed_titles_path(self, tmp_path: Path) -> None:
        mgr = ProjectManager(projects_root=tmp_path)
        mgr.create_project()

        path = mgr.parsed_titles("nursing")
        assert path.name == "parsed_titles.json"
        assert path.parent.name == "nursing"
        assert path.parent.parent.name == "02_analyze"

    def test_fingerprints_path(self, tmp_path: Path) -> None:
        mgr = ProjectManager(projects_root=tmp_path)
        mgr.create_project()

        path = mgr.fingerprints("nursing")
        assert path.name == "fingerprints.parquet"
        assert path.parent.name == "nursing"
        assert path.parent.parent.name == "02_analyze"

    def test_report_html_path(self, tmp_path: Path) -> None:
        mgr = ProjectManager(projects_root=tmp_path)
        mgr.create_project()

        path = mgr.report_html("nursing")
        assert path.name == "report.html"
        assert path.parent.name == "nursing"
        assert path.parent.parent.name == "03_report"

    def test_artifact_paths_isolate_aliases(self, tmp_path: Path) -> None:
        """Two aliases on the same project resolve to distinct directories."""
        mgr = ProjectManager(projects_root=tmp_path)
        mgr.create_project()

        nursing_videos = mgr.videos_meta("nursing")
        radiology_videos = mgr.videos_meta("radiology")
        assert nursing_videos != radiology_videos
        assert nursing_videos.parent.parent == radiology_videos.parent.parent


class TestRequiresActiveProject:
    """The new API raises if no project has been opened."""

    def test_stage_dir_without_project_raises(self, tmp_path: Path) -> None:
        from tube_scout.output.manager import Stage

        mgr = ProjectManager(projects_root=tmp_path)
        with pytest.raises(RuntimeError):
            mgr.stage_dir(Stage.COLLECT, "nursing")

    def test_videos_meta_without_project_raises(self, tmp_path: Path) -> None:
        mgr = ProjectManager(projects_root=tmp_path)
        with pytest.raises(RuntimeError):
            mgr.videos_meta("nursing")
