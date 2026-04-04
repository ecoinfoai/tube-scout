"""CLI helper for project directory resolution."""

from pathlib import Path

import typer

from tube_scout.output.manager import ProjectManager


def resolve_project(
    project_dir: str,
    project: str | None,
) -> ProjectManager:
    """Resolve or create a project from CLI options.

    Args:
        project_dir: Root directory for projects.
        project: None (new project), "latest", or explicit path.

    Returns:
        Configured ProjectManager with active project.

    Raises:
        typer.Exit: If latest has no symlink or path does not exist.
    """
    mgr = ProjectManager(projects_root=Path(project_dir))

    if project is None:
        mgr.create_project()
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
