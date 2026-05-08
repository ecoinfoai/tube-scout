"""RED + GREEN: services.title_parser.parse_and_save_titles.

Spec: idea6 / FR-IDEA6-003 / ADR-IDEA6-003 / T-IDEA6-D1.

A thin module-level helper that owns the
``TitleParser.parse_batch + save_results`` pair so callers (CLI,
web/jobs/runner) do not have to re-implement the orchestration.

Writes to the canonical
``projects/{ts}/02_analyze/{alias}/parsed_titles.json`` path via
``ProjectManager.parsed_titles(alias)``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tube_scout.output.manager import ProjectManager

SAMPLE_VIDEOS = [
    {"video_id": "abc123", "title": "[1주차] 인체구조 - 홍길동"},
    {"video_id": "def456", "title": "Random title"},
]


def test_helper_exists() -> None:
    from tube_scout.services.title_parser import parse_and_save_titles  # noqa: F401


def test_writes_canonical_path(tmp_path: Path) -> None:
    from tube_scout.services.title_parser import parse_and_save_titles

    mgr = ProjectManager(projects_root=tmp_path / "projects")
    mgr.create_project()

    out = parse_and_save_titles(
        videos=SAMPLE_VIDEOS, project_mgr=mgr, alias="nursing"
    )
    expected = mgr.parsed_titles("nursing")
    assert out == expected
    assert expected.exists()


def test_payload_round_trips(tmp_path: Path) -> None:
    from tube_scout.services.title_parser import parse_and_save_titles

    mgr = ProjectManager(projects_root=tmp_path / "projects")
    mgr.create_project()

    out = parse_and_save_titles(
        videos=SAMPLE_VIDEOS, project_mgr=mgr, alias="nursing"
    )
    data = json.loads(out.read_text(encoding="utf-8"))
    assert isinstance(data, list)
    assert len(data) == 2
    ids = {row["video_id"] for row in data}
    assert ids == {"abc123", "def456"}


def test_empty_videos_writes_empty_list(tmp_path: Path) -> None:
    """Empty input is NOT silently skipped — produces empty array file."""
    from tube_scout.services.title_parser import parse_and_save_titles

    mgr = ProjectManager(projects_root=tmp_path / "projects")
    mgr.create_project()

    out = parse_and_save_titles(videos=[], project_mgr=mgr, alias="nursing")
    assert out.exists()
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data == []


def test_alias_required(tmp_path: Path) -> None:
    """Empty alias fails fast (Constitution II)."""
    from tube_scout.services.title_parser import parse_and_save_titles

    mgr = ProjectManager(projects_root=tmp_path / "projects")
    mgr.create_project()
    with pytest.raises(ValueError):
        parse_and_save_titles(videos=SAMPLE_VIDEOS, project_mgr=mgr, alias="")
