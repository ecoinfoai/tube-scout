"""CLI helper for project directory resolution."""

from pathlib import Path

import typer

from tube_scout.output.manager import ProjectManager

# Spec-009 T028 producer set. Both `collect.videos` and `collect.all` may
# materialise a fresh project when invoked without `--project`: videos
# is the canonical producer, and `all` is a composite that orchestrates
# videos as its first stage and then routes the same project path into
# every consumer stage. Treating `collect.all` as a producer keeps the
# composite usable on a clean machine ("just run it") without forcing
# the operator to pre-run `collect videos` to seed `projects/latest`.
PRODUCER_COMMANDS: frozenset[str] = frozenset({"collect.videos", "collect.all"})


def is_producer(command_id: str) -> bool:
    """Return True iff command_id is a producer command.

    Args:
        command_id: Dot-separated CLI command identifier (e.g. "collect.videos").

    Returns:
        True if the command may create a new project; False otherwise.
    """
    return command_id in PRODUCER_COMMANDS


def resolve_project(
    project_dir: str,
    project: str | None,
    producer: bool = False,
) -> ProjectManager:
    """Resolve or create a project from CLI options.

    When ``project`` is None and ``producer=False`` (consumer), opens the
    existing latest project. Raises ``LatestProjectMissing`` if none exists.
    When ``project`` is None and ``producer=True``, creates a new project.

    Args:
        project_dir: Root directory for projects.
        project: None (default), "latest", or explicit path.
        producer: If True, create a new project when project is None.
            Only producer commands (see PRODUCER_COMMANDS) should pass True.

    Returns:
        Configured ProjectManager with active project.

    Raises:
        LatestProjectMissing: If consumer mode and no latest project exists.
        typer.Exit: If "latest" has no symlink or explicit path does not exist.
    """
    from tube_scout.cli.errors import LatestProjectMissing

    mgr = ProjectManager(projects_root=Path(project_dir))

    if project is None:
        if producer:
            mgr.create_project()
            return mgr
        # Consumer: open latest or raise
        latest = mgr.resolve_latest()
        if latest is None:
            raise LatestProjectMissing()
        mgr.open_project(latest)
        return mgr

    if project == "latest":
        latest = mgr.resolve_latest()
        if latest is None:
            raise typer.Exit(code=1)
        mgr.open_project(latest)
        return mgr

    path = Path(project)
    try:
        mgr.open_project(path)
    except FileNotFoundError:
        raise typer.Exit(code=1)
    return mgr
