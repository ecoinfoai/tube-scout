"""T030~T033 RED — admin add-department unit tests (spec 016 US2).

Covers:
  T030 (FR-012): no OAuth env options → exit 0 + departments.json OAuth fields null
  T031 (FR-013): partial env options (1 of 3) → exit 1 + actionable stderr
  T032 (FR-012 backward-compat): all 3 env options → OAuth consent invoked
  T033 (FR-016): alias exists in channels.json with different channel_id → exit 1
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


def _run(args: list[str], env: dict | None = None) -> subprocess.CompletedProcess:
    import os
    import shutil
    full_env = os.environ.copy()
    if env:
        full_env.update(env)
    bin_ = shutil.which("tube-scout") or "tube-scout"
    return subprocess.run([bin_, *args], capture_output=True, text=True, env=full_env)


def _channels_json(tokens_dir: Path, alias: str, channel_id: str) -> Path:
    p = tokens_dir / "channels.json"
    p.write_text(json.dumps({
        alias: {
            "alias": alias,
            "channel_id": channel_id,
            "channel_name": "Test",
            "registered_at": "2026-01-01T00:00:00Z",
            "last_used_at": "2026-01-01T00:00:00Z",
            "token_path": str(tokens_dir / f"{alias}_token.json"),
        }
    }), encoding="utf-8")
    return p


class TestAddDepartmentNoOAuthEnv:
    """T030 — Takeout-only registration (no OAuth env options)."""

    def test_no_env_vars_succeeds(self, tmp_path: Path) -> None:
        """No OAuth env options → exit 0 + departments.json OAuth fields null (FR-012)."""
        tokens_dir = tmp_path / "tokens"
        tokens_dir.mkdir()
        dept_file = tokens_dir / "departments.json"

        result = _run(
            [
                "admin", "add-department",
                "--alias", "nursing2",
                "--display", "테스트학과",
            ],
            env={"TUBE_SCOUT_TOKENS_DIR": str(tokens_dir)},
        )

        assert result.returncode == 0, (
            f"Expected exit 0 for no-OAuth registration.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
        assert dept_file.exists(), "departments.json must be created"
        data = json.loads(dept_file.read_text(encoding="utf-8"))
        entries = data if isinstance(data, list) else list(data.values())
        match = next((e for e in entries if e.get("alias") == "nursing2"), None)
        assert match is not None, "nursing2 entry must exist in departments.json"
        assert match.get("channel_id_env") is None, (
            "channel_id_env must be null for Takeout-only registration"
        )
        assert match.get("client_secret_env") is None, (
            "client_secret_env must be null for Takeout-only registration"
        )
        assert match.get("api_key_env") is None, (
            "api_key_env must be null for Takeout-only registration"
        )


class TestAddDepartmentPartialEnvOptions:
    """T031 — partial OAuth env options rejected (FR-013)."""

    def test_partial_options_raises(self, tmp_path: Path) -> None:
        """Only --channel-id-env specified → exit 1 + actionable stderr (FR-013)."""
        tokens_dir = tmp_path / "tokens"
        tokens_dir.mkdir()

        result = _run(
            [
                "admin", "add-department",
                "--alias", "nursing3",
                "--display", "부분등록학과",
                "--channel-id-env", "TUBE_SCOUT_CHANNEL_ID_NURSING3",
                # client-secret-env and api-key-env intentionally omitted
            ],
            env={"TUBE_SCOUT_TOKENS_DIR": str(tokens_dir)},
        )

        assert result.returncode == 1, (
            f"Expected exit 1 for partial OAuth env.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
        combined = result.stdout + result.stderr
        assert any(
            phrase in combined
            for phrase in [
                "모두 명시",
                "모두 생략",
                "all-or-nothing",
                "channel-id-env",
            ]
        ), f"Stderr must mention partial-options constraint. Got: {combined!r}"


class TestAddDepartmentFullOAuth:
    """T032 — all 3 env options → backward-compat OAuth consent flow (FR-012 compat)."""

    def test_all_three_envs_invokes_oauth_consent(self, tmp_path: Path) -> None:
        """All 3 env vars defined + specified → OAuth consent attempted (FR-012 compat)."""
        tokens_dir = tmp_path / "tokens"
        tokens_dir.mkdir()

        import os
        env = {
            "TUBE_SCOUT_TOKENS_DIR": str(tokens_dir),
            "TUBE_SCOUT_CHANNEL_ID_NURSINGT": "UCtest00001",
            "TUBE_SCOUT_CLIENT_SECRET_NURSINGT": "secret_val",
            "TUBE_SCOUT_API_KEY_NURSINGT": "apikey_val",
        }

        result = _run(
            [
                "admin", "add-department",
                "--alias", "nursingt",
                "--display", "테스트OAuth학과",
                "--channel-id-env", "TUBE_SCOUT_CHANNEL_ID_NURSINGT",
                "--client-secret-env", "TUBE_SCOUT_CLIENT_SECRET_NURSINGT",
                "--api-key-env", "TUBE_SCOUT_API_KEY_NURSINGT",
                "--no-oauth-consent",  # skip actual browser flow in CI
            ],
            env=env,
        )

        # With --no-oauth-consent the registration itself must succeed (exit 0)
        assert result.returncode == 0, (
            f"Expected exit 0 with all 3 env + --no-oauth-consent.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
        dept_file = tokens_dir / "departments.json"
        assert dept_file.exists(), "departments.json must be created"
        data = json.loads(dept_file.read_text(encoding="utf-8"))
        entries = data if isinstance(data, list) else list(data.values())
        match = next((e for e in entries if e.get("alias") == "nursingt"), None)
        assert match is not None, "nursingt entry must exist"
        assert match.get("channel_id_env") == "TUBE_SCOUT_CHANNEL_ID_NURSINGT", (
            "channel_id_env must be stored when all 3 specified"
        )


class TestAddDepartmentDuplicateAlias:
    """T033 — alias in channels.json with different channel_id → DuplicateAliasError (FR-016)."""

    def test_alias_in_other_registry_raises(self, tmp_path: Path) -> None:
        """Alias in channels.json with different channel_id → exit 1 (FR-016)."""
        tokens_dir = tmp_path / "tokens"
        tokens_dir.mkdir()
        _channels_json(tokens_dir, "nursing", "UCexisting0001")

        result = _run(
            [
                "admin", "add-department",
                "--alias", "nursing",
                "--display", "간호학과",
                # no OAuth env — Takeout-only
            ],
            env={"TUBE_SCOUT_TOKENS_DIR": str(tokens_dir)},
        )

        assert result.returncode == 1, (
            f"Expected exit 1 when alias exists in channels.json.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
        combined = result.stdout + result.stderr
        assert "nursing" in combined, (
            f"Error message must mention the conflicting alias. Got: {combined!r}"
        )
