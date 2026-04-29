"""US3 T084 — `tube-scout admin status` (RED).

Spec admin-cli.md §3. 6 cases — token expiry color coding, running jobs
count, alias filter, JSON output, operator action recording.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
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


def _seed_dept(alias: str) -> None:
    from tube_scout.web.repo.departments_repo import DepartmentsRepo

    DepartmentsRepo().add(
        {
            "alias": alias,
            "display_name": f"학과-{alias}",
            "channel_id_env": f"TUBE_SCOUT_CHANNEL_ID_{alias.upper()}",
            "client_secret_env": f"TUBE_SCOUT_CLIENT_SECRET_{alias.upper()}",
            "api_key_env": f"TUBE_SCOUT_API_KEY_{alias.upper()}",
            "registered_at": datetime.now(timezone.utc).isoformat(),
        }
    )


def _seed_token(alias: str, expires_in_days: int, cli_env: Path) -> None:
    """Write a fake OAuth token file with an expiry day offset."""
    tokens_dir = cli_env / "cfg" / "tokens"
    tokens_dir.mkdir(parents=True, exist_ok=True)
    expiry = datetime.now(timezone.utc) + timedelta(days=expires_in_days)
    (tokens_dir / f"{alias}_token.json").write_text(
        json.dumps(
            {
                "expires_at": expiry.isoformat(),
                "refresh_token": "fake-refresh",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _invoke(args: list[str]):
    from tube_scout.cli.main import app

    return CliRunner().invoke(app, args, catch_exceptions=False)


def test_status_flags_expired_tokens_red(cli_env: Path) -> None:
    _seed_dept("physiology")
    _seed_token("physiology", expires_in_days=-1, cli_env=cli_env)
    result = _invoke(["admin", "status"])
    assert result.exit_code == 0
    assert "만료" in result.output


def test_status_flags_near_expiry_yellow(cli_env: Path) -> None:
    _seed_dept("nursing")
    _seed_token("nursing", expires_in_days=3, cli_env=cli_env)
    result = _invoke(["admin", "status"])
    assert result.exit_code == 0
    assert "임박" in result.output or "남음" in result.output


def test_status_shows_running_jobs_count(cli_env: Path) -> None:
    from tube_scout.web.repo import jobs_repo

    _seed_dept("physiology")
    _seed_token("physiology", expires_in_days=10, cli_env=cli_env)
    repo = jobs_repo.JobsRepo()
    repo.insert_pending(
        {
            "job_id": "20260429-100000",
            "department_alias": "physiology",
            "professor_name": "홍길동",
            "course_name": "해부생리학",
            "period_start": "2026-04-01",
            "period_end": "2026-04-28",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "created_by": "ops",
        }
    )
    repo.transition_to(
        "20260429-100000", status="running", current_stage="listing"
    )
    result = _invoke(["admin", "status"])
    assert result.exit_code == 0
    assert "1" in result.output and ("진행" in result.output or "running" in result.output)


def test_status_alias_filter_returns_single(cli_env: Path) -> None:
    _seed_dept("physiology")
    _seed_dept("nursing")
    _seed_token("physiology", expires_in_days=10, cli_env=cli_env)
    _seed_token("nursing", expires_in_days=10, cli_env=cli_env)
    result = _invoke(["admin", "status", "--alias", "physiology"])
    assert result.exit_code == 0
    assert "physiology" in result.output
    assert "nursing" not in result.output


def test_status_json_output_contract(cli_env: Path) -> None:
    _seed_dept("physiology")
    _seed_token("physiology", expires_in_days=10, cli_env=cli_env)
    result = _invoke(["admin", "status", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert isinstance(payload, list)
    assert payload and "alias" in payload[0]


def test_status_records_operator_action(cli_env: Path) -> None:
    from tube_scout.web.repo import operator_actions_repo

    _seed_dept("physiology")
    _invoke(["admin", "status"])
    actions = operator_actions_repo.OperatorActionsRepo().list_recent(limit=10)
    assert any(a.action == "status_check" for a in actions)
