"""Tests for progress bar utility."""

from tube_scout.cli.progress import create_progress


class TestCreateProgress:
    """Tests for create_progress helper."""

    def test_returns_progress_instance(self) -> None:
        """create_progress returns a rich Progress instance."""
        from rich.progress import Progress

        progress = create_progress()
        assert isinstance(progress, Progress)

    def test_progress_has_columns(self) -> None:
        """Progress instance has expected column types."""
        from rich.progress import (
            BarColumn,
            SpinnerColumn,
            TextColumn,
            TimeRemainingColumn,
        )

        progress = create_progress()
        col_types = [type(c) for c in progress.columns]
        assert SpinnerColumn in col_types
        assert BarColumn in col_types
        assert TextColumn in col_types
        assert TimeRemainingColumn in col_types

    def test_progress_context_manager(self) -> None:
        """Progress works as context manager for iteration."""
        items = list(range(5))
        collected = []

        with create_progress() as progress:
            task = progress.add_task("Testing", total=len(items))
            for item in items:
                collected.append(item)
                progress.advance(task)

        assert collected == items

    def test_progress_empty_iteration(self) -> None:
        """Progress handles empty iteration gracefully."""
        collected = []

        with create_progress() as progress:
            task = progress.add_task("Empty", total=0)
            for item in []:
                collected.append(item)
                progress.advance(task)

        assert collected == []
