"""T037 RED — admin add-department contract (4-combination matrix, spec 016 US2).

Covers contracts/admin-add-department.md option matrix:
  A — Takeout-only (no env opts) → exit 0, OAuth fields null
  B — all 3 env opts + envs defined → exit 0 (with --no-oauth-consent)
  C — 1 of 3 env opts specified → exit 1
  D — 2 of 3 env opts specified → exit 1
  E — wrong alias format → exit 1
"""

from __future__ import annotations

import json
import subprocess
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


@pytest.fixture()
def tokens_env(tmp_path: Path) -> dict:
    tokens_dir = tmp_path / "tokens"
    tokens_dir.mkdir()
    return {"TUBE_SCOUT_TOKENS_DIR": str(tokens_dir), "_tokens_dir": str(tokens_dir)}


class TestAdminAddDepartmentContract:
    """T037 — 4-combination matrix from contracts/admin-add-department.md."""

    def test_combination_a_takeout_only_exit0(
        self, tmp_path: Path, tokens_env: dict
    ) -> None:
        """Combination A: no OAuth env opts → exit 0, null fields in departments.json."""
        env = {k: v for k, v in tokens_env.items() if not k.startswith("_")}
        tokens_dir = Path(tokens_env["_tokens_dir"])

        result = _run(
            ["admin", "add-department", "--alias", "dept-a", "--display", "학과A"],
            env=env,
        )
        assert result.returncode == 0, (
            f"Combination A must exit 0.\nstdout:{result.stdout}\nstderr:{result.stderr}"
        )
        dept_file = tokens_dir / "departments.json"
        assert dept_file.exists()
        data = json.loads(dept_file.read_text(encoding="utf-8"))
        entries = data if isinstance(data, list) else list(data.values())
        entry = next(e for e in entries if e.get("alias") == "dept-a")
        assert entry["channel_id_env"] is None, "channel_id_env must be null (Combination A)"
        assert entry["client_secret_env"] is None
        assert entry["api_key_env"] is None

    def test_combination_b_full_oauth_exit0(
        self, tmp_path: Path, tokens_env: dict
    ) -> None:
        """Combination B: all 3 env opts + vars defined + --no-oauth-consent → exit 0."""
        env = {k: v for k, v in tokens_env.items() if not k.startswith("_")}
        env.update({
            "TUBE_SCOUT_CHANNEL_ID_DEPTB": "UCdeptb001",
            "TUBE_SCOUT_CLIENT_SECRET_DEPTB": "secret",
            "TUBE_SCOUT_API_KEY_DEPTB": "apikey",
        })

        result = _run(
            [
                "admin", "add-department",
                "--alias", "dept-b",
                "--display", "학과B",
                "--channel-id-env", "TUBE_SCOUT_CHANNEL_ID_DEPTB",
                "--client-secret-env", "TUBE_SCOUT_CLIENT_SECRET_DEPTB",
                "--api-key-env", "TUBE_SCOUT_API_KEY_DEPTB",
                "--no-oauth-consent",
            ],
            env=env,
        )
        assert result.returncode == 0, (
            f"Combination B must exit 0.\nstdout:{result.stdout}\nstderr:{result.stderr}"
        )

    def test_combination_c_one_env_opt_exit1(
        self, tmp_path: Path, tokens_env: dict
    ) -> None:
        """Combination C: only 1 of 3 env opts specified → exit 1."""
        env = {k: v for k, v in tokens_env.items() if not k.startswith("_")}

        result = _run(
            [
                "admin", "add-department",
                "--alias", "dept-c",
                "--display", "학과C",
                "--channel-id-env", "TUBE_SCOUT_CHANNEL_ID_DEPTC",
            ],
            env=env,
        )
        assert result.returncode == 1, (
            f"Combination C (1 of 3) must exit 1.\n"
            f"stdout:{result.stdout}\nstderr:{result.stderr}"
        )

    def test_combination_d_two_env_opts_exit1(
        self, tmp_path: Path, tokens_env: dict
    ) -> None:
        """Combination D: 2 of 3 env opts specified → exit 1."""
        env = {k: v for k, v in tokens_env.items() if not k.startswith("_")}

        result = _run(
            [
                "admin", "add-department",
                "--alias", "dept-d",
                "--display", "학과D",
                "--channel-id-env", "TUBE_SCOUT_CHANNEL_ID_DEPTD",
                "--client-secret-env", "TUBE_SCOUT_CLIENT_SECRET_DEPTD",
            ],
            env=env,
        )
        assert result.returncode == 1, (
            f"Combination D (2 of 3) must exit 1.\n"
            f"stdout:{result.stdout}\nstderr:{result.stderr}"
        )
