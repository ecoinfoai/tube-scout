"""Timestamped output directory management."""

import os
import tempfile
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path


class Stage(StrEnum):
    """Canonical pipeline stages used by ``ProjectManager`` (ADR-IDEA6-001).

    Values are the literal sub-directory names beneath
    ``projects/{ts}/`` that the alias-aware API resolves to.
    """

    COLLECT = "01_collect"
    ANALYZE = "02_analyze"
    REPORT = "03_report"
    CHECKPOINTS = "checkpoints"


class ProjectManager:
    """Manages project-based directory structure under projects/.

    Structure:
        projects/
            YYYYMMDD-HHMMSS/
                01_collect/
                02_analyze/
                03_report/
                checkpoints/
            latest -> YYYYMMDD-HHMMSS/

    Args:
        projects_root: Root directory for projects. Defaults to
            TUBE_SCOUT_PROJECTS_DIR env var or ./projects.
    """

    STEP_COLLECT = "01_collect"
    STEP_ANALYZE = "02_analyze"
    STEP_REPORT = "03_report"
    STEP_CHECKPOINT = "checkpoints"

    def __init__(self, projects_root: Path | None = None) -> None:
        if projects_root is not None:
            self._root = Path(projects_root)
        else:
            env_dir = os.environ.get("TUBE_SCOUT_PROJECTS_DIR")
            self._root = Path(env_dir) if env_dir else Path("projects")
        self._project_dir: Path | None = None

    def create_project(self) -> Path:
        """Create a new timestamped project directory.

        Per ADR-IDEA6-006 (D-3 fix): does NOT update ``latest`` on its
        own. Writers must call :meth:`commit_latest` after persisting
        at least one artifact under ``01_collect/``.

        Returns:
            Path to the created project directory.
        """
        self._root.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        self._project_dir = self._root / timestamp
        self._project_dir.mkdir(parents=True, exist_ok=True)
        return self._project_dir

    def open_project(self, project_path: Path) -> None:
        """Open an existing project directory.

        Args:
            project_path: Path to the project directory.

        Raises:
            FileNotFoundError: If the directory does not exist.
        """
        if not project_path.exists():
            raise FileNotFoundError(
                f"Project directory not found: {project_path}"
            )
        self._project_dir = project_path

    def resolve_latest(self) -> Path | None:
        """Resolve the 'latest' symlink.

        Returns:
            Path to the latest project directory, or None if no symlink exists.
        """
        latest = self._root / "latest"
        if latest.is_symlink():
            return latest.resolve()
        return None

    @property
    def project_dir(self) -> Path:
        """Return the current project directory.

        Raises:
            RuntimeError: If no project has been created or opened.
        """
        if self._project_dir is None:
            raise RuntimeError(
                "No project active. Call create_project() or open_project() first."
            )
        return self._project_dir

    @property
    def collect_dir(self) -> Path:
        """Return 01_collect/ path, creating if needed."""
        path = self.project_dir / self.STEP_COLLECT
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def analyze_dir(self) -> Path:
        """Return 02_analyze/ path, creating if needed."""
        path = self.project_dir / self.STEP_ANALYZE
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def report_dir(self) -> Path:
        """Return 03_report/ path, creating if needed."""
        path = self.project_dir / self.STEP_REPORT
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def checkpoint_dir(self) -> Path:
        """Return checkpoints/ path, creating if needed."""
        path = self.project_dir / self.STEP_CHECKPOINT
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _update_latest_link(self) -> None:
        """Point projects/latest to current project."""
        latest = self._root / "latest"
        if latest.is_symlink() or latest.exists():
            latest.unlink()
        latest.symlink_to(self.project_dir.resolve())

    # ------------------------------------------------------------------
    # Alias-aware API (idea6 ADR-IDEA6-001)
    # ------------------------------------------------------------------

    def stage_dir(self, stage: Stage, alias: str) -> Path:
        """Return the alias-partitioned sub-directory for a pipeline stage.

        Args:
            stage: One of ``Stage.{COLLECT, ANALYZE, REPORT, CHECKPOINTS}``.
            alias: User-facing channel alias (per ADR-IDEA6-002).

        Returns:
            Path to ``project_dir/{stage}/{alias}/`` (created if missing).

        Raises:
            RuntimeError: If no project has been created or opened.
            ValueError: If ``alias`` contains path-traversal characters
                (``/``, ``\\``, ``..`` parts, leading ``.``, or absolute
                path) — A6-2 / FR-IDEA6-002 fail-fast guard.
        """
        # A6-2 (adversary P1) defensive sanitization.
        if not alias:
            raise ValueError(
                "stage_dir: alias must be a non-empty string (FR-IDEA6-002)."
            )
        if (
            "/" in alias
            or "\\" in alias
            or alias.startswith(".")
            or alias == ".."
            or Path(alias).is_absolute()
        ):
            raise ValueError(
                f"stage_dir: rejecting path-traversal alias {alias!r}. "
                "Aliases must be a single path component (FR-IDEA6-002, A6-2)."
            )
        base = self.project_dir / stage.value / alias
        # Defense-in-depth: ensure the resolved path stays inside project_dir.
        try:
            base.resolve().relative_to(self.project_dir.resolve())
        except ValueError as exc:  # pragma: no cover — guard above blocks this.
            raise ValueError(
                f"stage_dir: alias {alias!r} resolved outside project root."
            ) from exc
        base.mkdir(parents=True, exist_ok=True)
        return base

    def videos_meta(self, alias: str) -> Path:
        """Path to ``01_collect/{alias}/videos_meta.json`` (FR-IDEA6-001)."""
        return self.stage_dir(Stage.COLLECT, alias) / "videos_meta.json"

    def parsed_titles(self, alias: str) -> Path:
        """Path to ``02_analyze/{alias}/parsed_titles.json`` (FR-IDEA6-003)."""
        return self.stage_dir(Stage.ANALYZE, alias) / "parsed_titles.json"

    def fingerprints(self, alias: str) -> Path:
        """Path to ``02_analyze/{alias}/fingerprints.parquet`` (FR-IDEA6-001)."""
        return self.stage_dir(Stage.ANALYZE, alias) / "fingerprints.parquet"

    def report_html(self, alias: str) -> Path:
        """Path to ``03_report/{alias}/report.html`` (FR-IDEA6-001)."""
        return self.stage_dir(Stage.REPORT, alias) / "report.html"

    # ------------------------------------------------------------------
    # Atomic latest-symlink (idea6 ADR-IDEA6-006)
    # ------------------------------------------------------------------

    def _collect_has_artifact(self) -> bool:
        """Return True iff ``01_collect/`` contains at least one file."""
        collect_root = self.project_dir / Stage.COLLECT.value
        if not collect_root.exists():
            return False
        for path in collect_root.rglob("*"):
            if path.is_file():
                return True
        return False

    def commit_latest(self) -> None:
        """Atomically point ``projects/latest`` at the current project.

        Refuses to swap when the project's ``01_collect/`` is missing or
        empty (D-3 root cause). Uses ``tempfile + os.replace`` so the
        symlink swap is POSIX-atomic.

        Raises:
            UserFacingError: If no artifact has been written under
                ``01_collect/``. The hint points the operator at
                ``tube-scout admin repair-latest``.
        """
        from tube_scout.cli.errors import UserFacingError

        if not self._collect_has_artifact():
            raise UserFacingError(
                message=(
                    "Refusing to point projects/latest at an empty project "
                    f"({self.project_dir.name}). 01_collect/ must contain "
                    "at least one artifact before commit_latest()."
                ),
                next_command="tube-scout admin repair-latest",
            )
        target = self.project_dir.resolve()
        # tempfile.mktemp avoided; create unique symlink name in same dir
        # then os.replace for atomic swap.
        tmp_link = self._root / f".latest.tmp.{os.getpid()}.{datetime.now(UTC).strftime('%H%M%S%f')}"
        if tmp_link.exists() or tmp_link.is_symlink():
            tmp_link.unlink()
        tmp_link.symlink_to(target)
        latest = self._root / "latest"
        # os.replace works on symlinks since Python 3.3 (POSIX rename atomic).
        os.replace(tmp_link, latest)

    def resolve_latest_strict(self) -> Path:
        """Resolve ``latest`` and raise on empty / missing target.

        Returns:
            Path to the latest project directory.

        Raises:
            UserFacingError: If ``latest`` is absent or points at an
                empty project.
        """
        from tube_scout.cli.errors import UserFacingError

        latest = self._root / "latest"
        if not latest.is_symlink():
            raise UserFacingError(
                message="No projects/latest symlink — no project committed yet.",
                next_command="tube-scout admin repair-latest",
            )
        target = latest.resolve()
        collect_root = target / Stage.COLLECT.value
        if not collect_root.exists() or not any(collect_root.rglob("*")):
            raise UserFacingError(
                message=(
                    f"projects/latest points at an empty project ({target.name}). "
                    "D-3 stale-symlink — operator should rerun the most recent "
                    "successful collect, or repair the link."
                ),
                next_command="tube-scout admin repair-latest",
            )
        return target


class OutputManager:
    """Manages timestamped output directories with a latest symlink.

    Args:
        base_dir: Base directory for output. Defaults to TUBE_SCOUT_OUTPUT_DIR
            env var or ./output.
    """

    def __init__(self, base_dir: Path | None = None) -> None:
        if base_dir is not None:
            self.base_dir = Path(base_dir)
        else:
            env_dir = os.environ.get("TUBE_SCOUT_OUTPUT_DIR")
            self.base_dir = Path(env_dir) if env_dir else Path("output")

    def create_run(self) -> Path:
        """Create a new timestamped output directory.

        Returns:
            Path to the created directory (e.g., output/report-20260404-1211/).
        """
        self.base_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d-%H%M")
        run_dir = self.base_dir / f"report-{timestamp}"
        run_dir.mkdir(parents=True, exist_ok=True)
        return run_dir

    def update_latest_link(self, run_dir: Path) -> None:
        """Create or update the 'latest' symlink to point to run_dir.

        Args:
            run_dir: Path to the run directory to link to.
        """
        latest = self.base_dir / "latest"
        if latest.is_symlink() or latest.exists():
            latest.unlink()
        latest.symlink_to(run_dir.resolve())

    def get_latest(self) -> Path | None:
        """Resolve the 'latest' symlink.

        Returns:
            Path to the latest run directory, or None if no symlink exists.
        """
        latest = self.base_dir / "latest"
        if latest.is_symlink():
            return latest.resolve()
        return None
