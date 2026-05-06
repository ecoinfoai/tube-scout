"""RED integration test for collect retention --channel routing (T013).

Asserts that `collect retention --channel nursing --project latest`:
1. Reads tokens/nursing.json (alias-keyed token)
2. Never opens port 8080 (no browser-redirect listener)

All tests MUST fail until T019 wires alias routing into collect.py.

FR: FR-007 (alias-keyed token routing in collect commands)
"""

from __future__ import annotations

import socket
from pathlib import Path
from unittest.mock import MagicMock, patch, call
import json

import pytest
from typer.testing import CliRunner

from tube_scout.cli.main import app


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def project_env(tmp_path: Path):
    """Minimal project + token directory layout."""
    projects = tmp_path / "projects"
    projects.mkdir()
    project = projects / "nursing_2026-05-07"
    project.mkdir()

    videos_meta = project / "videos_meta.json"
    videos_meta.write_text(json.dumps([
        {"video_id": "abc123", "title": "Test Video", "channel_id": "UCnursing123"}
    ]))

    config_dir = tmp_path / "tube-scout"
    config_dir.mkdir()
    tokens_dir = config_dir / "tokens"
    tokens_dir.mkdir()

    token_data = {
        "token": "ya29.test-nursing",
        "refresh_token": "1//nursing-refresh",
        "token_uri": "https://oauth2.googleapis.com/token",
        "client_id": "test-client-id",
        "client_secret": "test-secret",
        "scopes": [
            "https://www.googleapis.com/auth/youtube.force-ssl",
            "https://www.googleapis.com/auth/yt-analytics.readonly",
        ],
    }
    alias_token = tokens_dir / "nursing.json"
    alias_token.write_text(json.dumps(token_data))

    channels_json = tokens_dir / "channels.json"
    channels_json.write_text(json.dumps({
        "nursing": {
            "alias": "nursing",
            "channel_id": "UCnursing123",
            "display_name": "Nursing Dept",
            "last_used": "2026-05-01T00:00:00+00:00",
        }
    }))

    return {"projects": projects, "project": project, "config_dir": config_dir, "alias_token": alias_token}


class TestCollectRetentionChannelFlag:
    def test_collect_retention_accepts_channel_flag(
        self, runner: CliRunner, project_env: dict
    ) -> None:
        """collect retention must accept --channel <alias> flag."""
        with patch("tube_scout.services.auth.build_analytics_client") as mock_build:
            mock_build.return_value = MagicMock()
            result = runner.invoke(
                app,
                [
                    "collect", "retention",
                    "--channel", "nursing",
                    "--project", str(project_env["project"]),
                    "--project-dir", str(project_env["projects"]),
                ],
            )
        assert result.exit_code != 2, f"CLI rejected --channel flag: {result.output}"

    def test_collect_retention_routes_to_alias_token(
        self, runner: CliRunner, project_env: dict
    ) -> None:
        """--channel nursing must cause authenticate_channel('nursing') to be called."""
        with patch("tube_scout.services.auth.authenticate_channel") as mock_auth:
            mock_auth.return_value = MagicMock()
            with patch("tube_scout.services.auth.build") as mock_build:
                mock_build.return_value = MagicMock()
                runner.invoke(
                    app,
                    [
                        "collect", "retention",
                        "--channel", "nursing",
                        "--project", str(project_env["project"]),
                        "--project-dir", str(project_env["projects"]),
                    ],
                )
        mock_auth.assert_called_with("nursing")

    def test_collect_retention_never_opens_port_8080(
        self, runner: CliRunner, project_env: dict, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Alias-based auth must not open port 8080 (no browser-redirect)."""
        binds: list = []
        original_bind = socket.socket.bind

        def tracking_bind(self, address):
            binds.append(address)
            return original_bind(self, address)

        monkeypatch.setattr(socket.socket, "bind", tracking_bind)

        with patch("tube_scout.services.auth.authenticate_channel", return_value=MagicMock()):
            with patch("tube_scout.services.auth.build", return_value=MagicMock()):
                runner.invoke(
                    app,
                    [
                        "collect", "retention",
                        "--channel", "nursing",
                        "--project", str(project_env["project"]),
                        "--project-dir", str(project_env["projects"]),
                    ],
                )

        port_8080_binds = [a for a in binds if isinstance(a, tuple) and len(a) >= 2 and a[1] == 8080]
        assert len(port_8080_binds) == 0, f"Unexpected port 8080 bind: {port_8080_binds}"


class TestCollectRetentionLatestProject:
    def test_collect_retention_channel_with_latest_project(
        self, runner: CliRunner, project_env: dict
    ) -> None:
        """--channel + --project latest must not fail with exit code 2."""
        with patch("tube_scout.services.auth.authenticate_channel", return_value=MagicMock()):
            with patch("tube_scout.services.auth.build", return_value=MagicMock()):
                result = runner.invoke(
                    app,
                    [
                        "collect", "retention",
                        "--channel", "nursing",
                        "--project", "latest",
                        "--project-dir", str(project_env["projects"]),
                    ],
                )
        assert result.exit_code != 2, f"CLI rejected --channel with --project latest: {result.output}"

    def test_collect_retention_invalid_alias_rejected(
        self, runner: CliRunner, project_env: dict
    ) -> None:
        """Invalid alias must produce a non-zero exit or clear error."""
        result = runner.invoke(
            app,
            [
                "collect", "retention",
                "--channel", "../evil",
                "--project", str(project_env["project"]),
                "--project-dir", str(project_env["projects"]),
            ],
        )
        assert result.exit_code != 0, "Expected non-zero exit for invalid alias"
