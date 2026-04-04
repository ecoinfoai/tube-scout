"""Shared progress bar utilities for CLI commands."""

from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeRemainingColumn,
)


def create_progress() -> Progress:
    """Create a consistently styled Progress instance.

    Returns:
        Configured rich Progress with spinner, description, bar, and ETA.
    """
    return Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TimeRemainingColumn(),
    )
