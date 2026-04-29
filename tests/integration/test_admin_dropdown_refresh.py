"""US3 T088 — admin add-department triggers web dropdown refresh (RED).

Spec FR-025: when the operator adds a new department via CLI while the
web app is running, the next ``GET /jobs/new`` MUST surface the new
alias in the dropdown without a server restart. Backed by
``DepartmentsRepo`` mtime cache invalidation.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

import bcrypt
import pytest
from httpx import ASGITransport, AsyncClient
from typer.testing import CliRunner

USERNAME = "ops"
PASSWORD = "S3cret-Pass!"


@pytest.fixture
def cli_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    pw_hash = bcrypt.hashpw(PASSWORD.encode(), bcrypt.gensalt(rounds=4)).decode()
    monkeypatch.setenv("TUBE_SCOUT_ADMIN_USERNAME", USERNAME)
    monkeypatch.setenv("TUBE_SCOUT_ADMIN_PASSWORD_BCRYPT", pw_hash)
    monkeypatch.setenv("TUBE_SCOUT_SESSION_SECRET", "x" * 32)
    monkeypatch.setenv("TUBE_SCOUT_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("TUBE_SCOUT_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("TUBE_SCOUT_CHANNEL_ID_NEWDEPT", "UCxxxxxxxxxxxx")
    monkeypatch.setenv("TUBE_SCOUT_CLIENT_SECRET_NEWDEPT", "secret")
    monkeypatch.setenv("TUBE_SCOUT_API_KEY_NEWDEPT", "api-key")
    (tmp_path / "state").mkdir(parents=True, exist_ok=True)
    (tmp_path / "cfg").mkdir(parents=True, exist_ok=True)
    from tube_scout.web.repo import db

    db.bootstrap()
    return tmp_path


async def test_add_department_via_cli_refreshes_jobs_new_dropdown(
    cli_env: Path,
) -> None:
    from tube_scout.cli.main import app as cli_app
    from tube_scout.web.app import create_app

    web_app = create_app()
    runner = CliRunner()

    async with AsyncClient(
        transport=ASGITransport(app=web_app),
        base_url="https://test",
        follow_redirects=False,
    ) as client:
        async with web_app.router.lifespan_context(web_app):
            # 1. Authenticate.
            form = await client.get("/login")
            csrf = re.search(
                r'name="csrf_token"\s+value="([0-9a-f]{32})"', form.text
            ).group(1)
            login = await client.post(
                "/login",
                data={"username": USERNAME, "password": PASSWORD, "csrf_token": csrf},
            )
            assert login.status_code in {302, 303}

            # 2. Sanity: dropdown initially has no entry for newdept.
            initial = await client.get("/jobs/new")
            assert initial.status_code == 200
            assert "newdept" not in initial.text

            # 3. Add a new department through the CLI.
            result = runner.invoke(
                cli_app,
                [
                    "admin",
                    "add-department",
                    "--alias",
                    "newdept",
                    "--display",
                    "신규학과",
                    "--channel-id-env",
                    "TUBE_SCOUT_CHANNEL_ID_NEWDEPT",
                    "--client-secret-env",
                    "TUBE_SCOUT_CLIENT_SECRET_NEWDEPT",
                    "--api-key-env",
                    "TUBE_SCOUT_API_KEY_NEWDEPT",
                    "--no-oauth-consent",
                ],
                catch_exceptions=False,
            )
            assert result.exit_code == 0, result.output

            # 4. Next /jobs/new request MUST show the new alias.
            updated = await client.get("/jobs/new")
            assert updated.status_code == 200
            assert "newdept" in updated.text
            assert "신규학과" in updated.text
