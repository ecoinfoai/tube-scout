"""Timestamped output directory management."""

import os
from datetime import UTC, datetime
from pathlib import Path


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

        Returns:
            Path to the created project directory.
        """
        self._root.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        self._project_dir = self._root / timestamp
        self._project_dir.mkdir(parents=True, exist_ok=True)
        self._update_latest_link()
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
