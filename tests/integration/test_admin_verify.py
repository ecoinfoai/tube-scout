"""US3 T086 — `tube-scout admin verify` (RED).

Spec admin-cli.md §5. 4 cases.
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
    monkeypatch.setenv("TUBE_SCOUT_CHANNEL_ID_PHYSIOLOGY", "UCxxxxxxxxxxxx")
    monkeypatch.setenv("TUBE_SCOUT_CLIENT_SECRET_PHYSIOLOGY", "secret")
    monkeypatch.setenv("TUBE_SCOUT_API_KEY_PHYSIOLOGY", "api-key")
    (tmp_path / "state").mkdir(parents=True, exist_ok=True)
    (tmp_path / "cfg").mkdir(parents=True, exist_ok=True)
    from tube_scout.web.repo import db

    db.bootstrap()
    return tmp_path


def _seed_dept() -> None:
    from tube_scout.web.repo.departments_repo import DepartmentsRepo

    DepartmentsRepo().add(
        {
            "alias": "physiology",
            "display_name": "물리치료과",
            "channel_id_env": "TUBE_SCOUT_CHANNEL_ID_PHYSIOLOGY",
            "client_secret_env": "TUBE_SCOUT_CLIENT_SECRET_PHYSIOLOGY",
            "api_key_env": "TUBE_SCOUT_API_KEY_PHYSIOLOGY",
            "registered_at": datetime.now(UTC).isoformat(),
        }
    )


def _seed_token(days: int, cli_env: Path) -> None:
    tokens_dir = cli_env / "cfg" / "tokens"
    tokens_dir.mkdir(parents=True, exist_ok=True)
    expiry = datetime.now(UTC) + timedelta(days=days)
    (tokens_dir / "physiology_token.json").write_text(
        json.dumps(
            {"expires_at": expiry.isoformat(), "refresh_token": "rf"},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _invoke(args: list[str]):
    from tube_scout.cli.main import app

    return CliRunner().invoke(app, args, catch_exceptions=False)


def test_verify_all_steps_pass_returns_zero(
    cli_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_dept()
    _seed_token(days=30, cli_env=cli_env)

    monkeypatch.setattr(
        "tube_scout.cli.admin._youtube_api_probe",
        lambda alias, channel_id: {"channel_name": "Test"},
        raising=False,
    )

    result = _invoke(["admin", "verify", "physiology"])
    assert result.exit_code == 0


def test_verify_missing_env_var_fails_with_kr_message(
    cli_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_dept()
    monkeypatch.delenv("TUBE_SCOUT_CHANNEL_ID_PHYSIOLOGY", raising=False)
    result = _invoke(["admin", "verify", "physiology"])
    assert result.exit_code == 1
    assert "환경변수" in result.output


def test_verify_invalid_token_fails_at_step_5(
    cli_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_dept()
    _seed_token(days=-1, cli_env=cli_env)
    result = _invoke(["admin", "verify", "physiology"])
    assert result.exit_code == 1


def test_verify_api_quota_exceeded_reports_kr_message(
    cli_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_dept()
    _seed_token(days=30, cli_env=cli_env)

    def boom(alias, channel_id):
        raise RuntimeError("quotaExceeded")

    monkeypatch.setattr("tube_scout.cli.admin._youtube_api_probe", boom, raising=False)
    result = _invoke(["admin", "verify", "physiology"])
    assert result.exit_code == 1
    assert "할당량" in result.output or "quota" in result.output.lower()
