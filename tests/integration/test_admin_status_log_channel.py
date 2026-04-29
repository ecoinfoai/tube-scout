"""US3 T087 — admin status log channel (RED).

Spec Q3 / FR-026: token expiry detection MUST emit a structured log line
to ``$LOG_DIR/admin-status.log``. The line is JSON so journald or a
log shipper can index it.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
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
            "registered_at": datetime.now(UTC).isoformat(),
        }
    )


def _seed_expired_token(alias: str, cli_env: Path) -> None:
    tokens_dir = cli_env / "cfg" / "tokens"
    tokens_dir.mkdir(parents=True, exist_ok=True)
    expiry = datetime.now(UTC) - timedelta(days=1)
    (tokens_dir / f"{alias}_token.json").write_text(
        json.dumps(
            {"expires_at": expiry.isoformat(), "refresh_token": "rf"},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _invoke(args: list[str]):
    from tube_scout.cli.main import app

    return CliRunner().invoke(app, args, catch_exceptions=False)


def test_status_writes_structured_log_on_token_expiry(cli_env: Path) -> None:
    _seed_dept("physiology")
    _seed_expired_token("physiology", cli_env)

    result = _invoke(["admin", "status"])
    assert result.exit_code == 0

    from tube_scout.web.paths import get_log_dir

    log_path = get_log_dir() / "admin-status.log"
    assert log_path.is_file(), f"expected log at {log_path}"
    lines = [
        line
        for line in log_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert lines, "no log lines written"
    last = json.loads(lines[-1])
    assert last.get("alias") == "physiology"
    assert last.get("token_status") in {"expired", "needs_refresh"}
