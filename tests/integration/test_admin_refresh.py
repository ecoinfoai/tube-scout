"""US3 T085 — `tube-scout admin refresh` (RED).

Spec admin-cli.md §4. 4 cases.
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


def _seed_dept(alias: str = "physiology") -> None:
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


def _seed_token(alias: str, days: int, cli_env: Path) -> None:
    tokens_dir = cli_env / "cfg" / "tokens"
    tokens_dir.mkdir(parents=True, exist_ok=True)
    expiry = datetime.now(timezone.utc) + timedelta(days=days)
    (tokens_dir / f"{alias}_token.json").write_text(
        json.dumps(
            {"expires_at": expiry.isoformat(), "refresh_token": "fake-refresh"},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _invoke(args: list[str]):
    from tube_scout.cli.main import app

    return CliRunner().invoke(app, args, catch_exceptions=False)


def test_refresh_unknown_alias_rejected(cli_env: Path) -> None:
    result = _invoke(["admin", "refresh", "unknown-alias"])
    assert result.exit_code == 1
    assert "등록되지 않은" in result.output or "찾을 수 없습니다" in result.output


def test_refresh_skips_valid_token_without_force(
    cli_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_dept("physiology")
    _seed_token("physiology", days=20, cli_env=cli_env)

    refresh_called: list[bool] = []

    def fake_refresh(*args, **kwargs):
        refresh_called.append(True)

    monkeypatch.setattr(
        "tube_scout.cli.admin._refresh_token", fake_refresh, raising=False
    )

    result = _invoke(["admin", "refresh", "physiology"])
    assert result.exit_code == 0
    assert not refresh_called


def test_refresh_force_renews_anyway(
    cli_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_dept("physiology")
    _seed_token("physiology", days=20, cli_env=cli_env)

    refresh_called: list[bool] = []

    def fake_refresh(*args, **kwargs):
        refresh_called.append(True)

    monkeypatch.setattr(
        "tube_scout.cli.admin._refresh_token", fake_refresh, raising=False
    )

    result = _invoke(["admin", "refresh", "physiology", "--force"])
    assert result.exit_code == 0
    assert refresh_called


def test_refresh_records_failure_on_invalid_grant(
    cli_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tube_scout.web.repo import operator_actions_repo

    _seed_dept("physiology")
    _seed_token("physiology", days=-1, cli_env=cli_env)

    def boom(*args, **kwargs):
        raise RuntimeError("invalid_grant")

    monkeypatch.setattr(
        "tube_scout.cli.admin._refresh_token", boom, raising=False
    )

    result = _invoke(["admin", "refresh", "physiology"])
    assert result.exit_code == 1

    actions = operator_actions_repo.OperatorActionsRepo().list_recent(limit=10)
    fails = [a for a in actions if a.action == "token_refresh" and a.result == "failure"]
    assert fails
