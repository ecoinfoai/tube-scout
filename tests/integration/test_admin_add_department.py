"""US3 T082 — `tube-scout admin add-department` (RED).

Spec FR-024 + admin-cli.md §1. The command is not yet wired so all 6
cases fail until cli/admin.py + cli/main.py app.add_typer land (T089/T090).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner


@pytest.fixture
def cli_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Configure CONFIG/STATE dirs + the agenix env vars used by the test alias."""
    monkeypatch.setenv("TUBE_SCOUT_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("TUBE_SCOUT_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("TUBE_SCOUT_CHANNEL_ID_PHYS", "UCxxxxxxxxxxxxxx")
    monkeypatch.setenv("TUBE_SCOUT_CLIENT_SECRET_PHYS", "client-secret-blob")
    monkeypatch.setenv("TUBE_SCOUT_API_KEY_PHYS", "api-key-blob")
    (tmp_path / "state").mkdir(parents=True, exist_ok=True)
    (tmp_path / "cfg").mkdir(parents=True, exist_ok=True)
    from tube_scout.web.repo import db

    db.bootstrap()
    return tmp_path


def _runner_invoke(args: list[str]) -> object:
    from tube_scout.cli.main import app

    runner = CliRunner()
    return runner.invoke(app, args, catch_exceptions=False)


def test_add_department_writes_departments_json(cli_env: Path) -> None:
    result = _runner_invoke(
        [
            "admin",
            "add-department",
            "--alias",
            "physiology",
            "--display",
            "물리치료과",
            "--channel-id-env",
            "TUBE_SCOUT_CHANNEL_ID_PHYS",
            "--client-secret-env",
            "TUBE_SCOUT_CLIENT_SECRET_PHYS",
            "--api-key-env",
            "TUBE_SCOUT_API_KEY_PHYS",
            "--no-oauth-consent",
        ]
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(
        (cli_env / "cfg" / "departments.json").read_text(encoding="utf-8")
    )
    aliases = [d["alias"] for d in payload["departments"]]
    assert "physiology" in aliases


def test_add_department_rejects_duplicate_alias(cli_env: Path) -> None:
    args = [
        "admin",
        "add-department",
        "--alias",
        "physiology",
        "--display",
        "물리치료과",
        "--channel-id-env",
        "TUBE_SCOUT_CHANNEL_ID_PHYS",
        "--client-secret-env",
        "TUBE_SCOUT_CLIENT_SECRET_PHYS",
        "--api-key-env",
        "TUBE_SCOUT_API_KEY_PHYS",
        "--no-oauth-consent",
    ]
    first = _runner_invoke(args)
    assert first.exit_code == 0, first.output
    second = _runner_invoke(args)
    assert second.exit_code == 1
    assert "이미" in second.output or "중복" in second.output


def test_add_department_validates_alias_pattern(cli_env: Path) -> None:
    result = _runner_invoke(
        [
            "admin",
            "add-department",
            "--alias",
            "INVALID-CAPITAL",  # uppercase rejected by regex
            "--display",
            "테스트",
            "--channel-id-env",
            "TUBE_SCOUT_CHANNEL_ID_PHYS",
            "--client-secret-env",
            "TUBE_SCOUT_CLIENT_SECRET_PHYS",
            "--api-key-env",
            "TUBE_SCOUT_API_KEY_PHYS",
            "--no-oauth-consent",
        ]
    )
    assert result.exit_code == 1


def test_add_department_fails_when_env_missing(
    cli_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("TUBE_SCOUT_CHANNEL_ID_PHYS", raising=False)
    result = _runner_invoke(
        [
            "admin",
            "add-department",
            "--alias",
            "physiology",
            "--display",
            "물리치료과",
            "--channel-id-env",
            "TUBE_SCOUT_CHANNEL_ID_PHYS",
            "--client-secret-env",
            "TUBE_SCOUT_CLIENT_SECRET_PHYS",
            "--api-key-env",
            "TUBE_SCOUT_API_KEY_PHYS",
            "--no-oauth-consent",
        ]
    )
    assert result.exit_code == 1
    assert "환경변수" in result.output


def test_add_department_records_operator_action(cli_env: Path) -> None:
    from tube_scout.web.repo import operator_actions_repo

    _runner_invoke(
        [
            "admin",
            "add-department",
            "--alias",
            "physiology",
            "--display",
            "물리치료과",
            "--channel-id-env",
            "TUBE_SCOUT_CHANNEL_ID_PHYS",
            "--client-secret-env",
            "TUBE_SCOUT_CLIENT_SECRET_PHYS",
            "--api-key-env",
            "TUBE_SCOUT_API_KEY_PHYS",
            "--no-oauth-consent",
        ]
    )
    actions = operator_actions_repo.OperatorActionsRepo().list_recent(limit=10)
    actions_kinds = [a.action for a in actions]
    assert "add_department" in actions_kinds


def test_add_department_no_oauth_consent_flag_skips_browser(
    cli_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``--no-oauth-consent`` MUST avoid invoking the OAuth flow."""
    consent_called: list[bool] = []

    def fake_consent(*args, **kwargs):
        consent_called.append(True)

    monkeypatch.setattr(
        "tube_scout.cli.admin._run_oauth_consent",
        fake_consent,
        raising=False,
    )

    result = _runner_invoke(
        [
            "admin",
            "add-department",
            "--alias",
            "physiology",
            "--display",
            "물리치료과",
            "--channel-id-env",
            "TUBE_SCOUT_CHANNEL_ID_PHYS",
            "--client-secret-env",
            "TUBE_SCOUT_CLIENT_SECRET_PHYS",
            "--api-key-env",
            "TUBE_SCOUT_API_KEY_PHYS",
            "--no-oauth-consent",
        ]
    )
    assert result.exit_code == 0, result.output
    assert not consent_called
