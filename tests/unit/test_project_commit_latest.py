"""RED + GREEN: ProjectManager.commit_latest atomic + empty guard.

Spec: idea6 / FR-IDEA6-006 / ADR-IDEA6-006 / T-IDEA6-B1.

Reproduces D-3 ("projects/latest pointing at an empty project") and
asserts the new behaviour: ``create_project()`` no longer touches
``latest`` on its own; the writer must call ``commit_latest()`` after
persisting at least one artifact under ``01_collect/``. The swap is
atomic via ``tempfile + os.replace``.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from tube_scout.output.manager import ProjectManager, Stage


def _make_manager(tmp_path: Path) -> ProjectManager:
    return ProjectManager(projects_root=tmp_path / "projects")


class TestCreateProjectDoesNotUpdateLatest:
    """``create_project()`` MUST NOT update ``latest`` (D-3 root cause)."""

    def test_create_does_not_update_latest(self, tmp_path: Path) -> None:
        mgr = _make_manager(tmp_path)
        mgr.create_project()
        assert mgr.resolve_latest() is None, (
            "create_project should no longer touch latest; "
            "operator must call commit_latest() after writing artifacts"
        )


class TestCommitLatestEmptyGuard:
    """``commit_latest()`` refuses to point latest at an empty project."""

    def test_commit_latest_raises_when_collect_missing(
        self, tmp_path: Path
    ) -> None:
        from tube_scout.cli.errors import UserFacingError

        mgr = _make_manager(tmp_path)
        mgr.create_project()
        with pytest.raises(UserFacingError) as exc_info:
            mgr.commit_latest()
        assert "empty" in exc_info.value.message.lower() or "01_collect" in exc_info.value.message

    def test_commit_latest_raises_when_collect_empty(
        self, tmp_path: Path
    ) -> None:
        from tube_scout.cli.errors import UserFacingError

        mgr = _make_manager(tmp_path)
        mgr.create_project()
        # touch only the dir but no artifact
        mgr.stage_dir(Stage.COLLECT, "nursing")
        with pytest.raises(UserFacingError):
            mgr.commit_latest()


class TestCommitLatestAtomic:
    """``commit_latest()`` performs an atomic ``tempfile + os.replace`` swap."""

    def test_commit_latest_succeeds_when_collect_populated(
        self, tmp_path: Path
    ) -> None:
        mgr = _make_manager(tmp_path)
        proj = mgr.create_project()
        mgr.videos_meta("nursing").write_text("[]", encoding="utf-8")
        mgr.commit_latest()
        latest = mgr.resolve_latest()
        assert latest is not None
        assert latest == proj.resolve()

    def test_commit_latest_replaces_previous(self, tmp_path: Path) -> None:
        import time

        mgr1 = _make_manager(tmp_path)
        proj1 = mgr1.create_project()
        mgr1.videos_meta("nursing").write_text("[]", encoding="utf-8")
        mgr1.commit_latest()

        # ProjectManager uses second-precision timestamps; ensure a
        # distinct directory for the second run.
        time.sleep(1.05)

        mgr2 = _make_manager(tmp_path)
        proj2 = mgr2.create_project()
        mgr2.videos_meta("nursing").write_text("[1]", encoding="utf-8")
        mgr2.commit_latest()

        latest = mgr2.resolve_latest()
        assert latest == proj2.resolve()
        assert latest != proj1.resolve()


class TestResolveLatestRaisesOnEmpty:
    """``resolve_latest`` returns None when latest absent; raises on empty."""

    def test_resolve_latest_none_when_absent(self, tmp_path: Path) -> None:
        mgr = _make_manager(tmp_path)
        assert mgr.resolve_latest() is None

    def test_resolve_latest_raises_for_stale_empty(
        self, tmp_path: Path
    ) -> None:
        from tube_scout.cli.errors import UserFacingError

        mgr = _make_manager(tmp_path)
        proj = mgr.create_project()
        # Manually create a broken latest -> empty project
        latest = (tmp_path / "projects" / "latest")
        latest.symlink_to(proj.resolve())
        with pytest.raises(UserFacingError) as exc_info:
            mgr.resolve_latest_strict()
        assert "repair-latest" in exc_info.value.next_command
