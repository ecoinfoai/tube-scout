"""Tests for Jupyter Notebook export (T059a)."""

from pathlib import Path
from typing import Any

import nbformat
import pytest

from tube_scout.reporting.notebook_export import VideoNotebookExporter


@pytest.fixture
def sample_video() -> dict[str, Any]:
    """Sample video metadata."""
    return {
        "video_id": "vid001",
        "title": "Test Lecture",
        "channel_id": "UCxxxxxxxxxxxxxxxxxxxxxx",
        "duration_seconds": 1800,
        "view_count": 5000,
        "like_count": 200,
    }


@pytest.fixture
def sample_retention() -> dict[str, Any]:
    """Sample retention analysis."""
    return {
        "video_id": "vid001",
        "hotspots": [
            {"elapsed_ratio": 0.3, "audience_watch_ratio": 1.5},
        ],
        "skip_zones": [
            {"elapsed_ratio": 0.8, "audience_watch_ratio": 0.4},
        ],
        "total_data_points": 100,
    }


@pytest.fixture
def sample_segments() -> list[dict[str, Any]]:
    """Sample transcript segments."""
    return [
        {
            "segment_index": 0,
            "title": "Introduction",
            "start_seconds": 0.0,
            "end_seconds": 300.0,
            "difficulty_score": 0.2,
            "summary": "Overview of the topic.",
        },
        {
            "segment_index": 1,
            "title": "Core Concepts",
            "start_seconds": 300.0,
            "end_seconds": 1200.0,
            "difficulty_score": 0.8,
            "summary": "Main content.",
        },
    ]


class TestVideoNotebookExporter:
    """Tests for VideoNotebookExporter (T059a)."""

    def test_generates_valid_notebook(
        self,
        tmp_path: Path,
        sample_video: dict[str, Any],
        sample_retention: dict[str, Any],
        sample_segments: list[dict[str, Any]],
    ) -> None:
        exporter = VideoNotebookExporter()
        output_path = exporter.export(
            video=sample_video,
            retention=sample_retention,
            segments=sample_segments,
            output_dir=tmp_path,
        )
        assert output_path.exists()
        assert output_path.suffix == ".ipynb"

        # Validate notebook structure
        nb = nbformat.read(str(output_path), as_version=4)
        assert nb.nbformat == 4
        assert len(nb.cells) > 0

        # Should have markdown and code cells
        cell_types = {c.cell_type for c in nb.cells}
        assert "markdown" in cell_types
        assert "code" in cell_types

    def test_notebook_contains_video_title(
        self,
        tmp_path: Path,
        sample_video: dict[str, Any],
    ) -> None:
        exporter = VideoNotebookExporter()
        output_path = exporter.export(
            video=sample_video,
            retention=None,
            segments=None,
            output_dir=tmp_path,
        )
        nb = nbformat.read(str(output_path), as_version=4)
        # First cell should be markdown with video title
        assert nb.cells[0].cell_type == "markdown"
        assert "Test Lecture" in nb.cells[0].source

    def test_notebook_has_plotly_chart_cell(
        self,
        tmp_path: Path,
        sample_video: dict[str, Any],
        sample_retention: dict[str, Any],
    ) -> None:
        exporter = VideoNotebookExporter()
        output_path = exporter.export(
            video=sample_video,
            retention=sample_retention,
            segments=None,
            output_dir=tmp_path,
        )
        nb = nbformat.read(str(output_path), as_version=4)
        code_cells = [c for c in nb.cells if c.cell_type == "code"]
        # At least one code cell should contain plotly
        plotly_cells = [c for c in code_cells if "plotly" in c.source]
        assert len(plotly_cells) >= 1

    def test_notebook_handles_missing_data(
        self,
        tmp_path: Path,
        sample_video: dict[str, Any],
    ) -> None:
        exporter = VideoNotebookExporter()
        output_path = exporter.export(
            video=sample_video,
            retention=None,
            segments=None,
            output_dir=tmp_path,
        )
        assert output_path.exists()
        nb = nbformat.read(str(output_path), as_version=4)
        assert len(nb.cells) > 0

    def test_output_filename(
        self,
        tmp_path: Path,
        sample_video: dict[str, Any],
    ) -> None:
        exporter = VideoNotebookExporter()
        output_path = exporter.export(
            video=sample_video,
            retention=None,
            segments=None,
            output_dir=tmp_path,
        )
        assert output_path.name == "vid001.ipynb"
