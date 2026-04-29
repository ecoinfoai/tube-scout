"""US3 T083 — `tube-scout admin list` (RED).

Spec admin-cli.md §2. 3 cases.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner


@pytest.fixture
def cli_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setenv("TUBE_SCOUT_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("TUBE_SCOUT_CONFIG_DIR", str(tmp_path / "cfg"))
    (tmp_path / "state").mkdir(parents=True, exist_ok=True)
    (tmp_path / "cfg").mkdir(parents=True, exist_ok=True)
    from tube_scout.web.repo import db

    db.bootstrap()
    return tmp_path


def _seed(alias: str = "physiology") -> None:
    from tube_scout.web.repo.departments_repo import DepartmentsRepo

    DepartmentsRepo().add(
        {
            "alias": alias,
            "display_name": f"학과-{alias}",
            "channel_id_env": f"TUBE_SCOUT_CHANNEL_ID_{alias.upper()}",
            "client_secret_env": f"TUBE_SCOUT_CLIENT_SECRET_{alias.upper()}",
            "api_key_env": f"TUBE_SCOUT_API_KEY_{alias.upper()}",
            "registered_at": datetime.now(UTC).isoformat(),
        }
    )


def _invoke(args: list[str]):
    from tube_scout.cli.main import app

    return CliRunner().invoke(app, args, catch_exceptions=False)


def test_list_outputs_registered_departments(cli_env: Path) -> None:
    _seed("physiology")
    _seed("nursing")
    result = _invoke(["admin", "list"])
    assert result.exit_code == 0
    assert "physiology" in result.output
    assert "nursing" in result.output


def test_list_json_flag_returns_machine_readable(cli_env: Path) -> None:
    _seed("physiology")
    result = _invoke(["admin", "list", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    aliases = [d["alias"] for d in payload]
    assert "physiology" in aliases


def test_list_no_departments_shows_empty_message(cli_env: Path) -> None:
    result = _invoke(["admin", "list"])
    assert result.exit_code == 0
    assert "등록된 학과" in result.output or "없습니다" in result.output
