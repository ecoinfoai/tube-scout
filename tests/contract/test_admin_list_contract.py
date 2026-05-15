"""T038 RED — admin list contract (Rich table + JSON + stderr WARNING, spec 016 US2).

Covers contracts/admin-list.md:
  - Rich table output with source + consistency columns
  - JSON output with source + consistency fields per row
  - stderr WARNING when mismatch detected
  - exit 0 always (even with mismatch)
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


def _write_channels_json(tokens_dir: Path, alias: str, channel_id: str) -> None:
    data = {
        alias: {
            "alias": alias,
            "channel_id": channel_id,
            "channel_name": "테스트채널",
            "registered_at": "2026-01-01T00:00:00Z",
            "last_used_at": "2026-01-01T00:00:00Z",
            "token_path": str(tokens_dir / f"{alias}_token.json"),
        }
    }
    (tokens_dir / "channels.json").write_text(json.dumps(data), encoding="utf-8")


def _write_departments_json(tokens_dir: Path, entries: list[dict]) -> None:
    (tokens_dir / "departments.json").write_text(
        json.dumps(entries), encoding="utf-8"
    )


class TestAdminListContract:
    """T038 — contracts/admin-list.md full contract verification."""

    def test_json_output_has_source_and_consistency_fields(
        self, tmp_path: Path
    ) -> None:
        """--json output has source + consistency fields on every row (FR-014/015)."""
        tokens_dir = tmp_path / "tokens"
        tokens_dir.mkdir()
        _write_channels_json(tokens_dir, "nursing", "UCnursing001")
        _write_departments_json(tokens_dir, [
            {
                "alias": "nursing2",
                "display_name": "테스트학과",
                "channel_id_env": None,
                "client_secret_env": None,
                "api_key_env": None,
                "registered_at": "2026-01-01T00:00:00Z",
            }
        ])

        result = _run(
            ["admin", "list", "--json"],
            env={"TUBE_SCOUT_TOKENS_DIR": str(tokens_dir)},
        )

        assert result.returncode == 0, (
            f"admin list --json must exit 0.\nstdout:{result.stdout}\nstderr:{result.stderr}"
        )
        rows = json.loads(result.stdout)
        assert len(rows) == 2, f"Expected 2 rows (union), got {len(rows)}"
        for row in rows:
            assert "source" in row, f"Row missing 'source' field: {row}"
            assert "consistency" in row, f"Row missing 'consistency' field: {row}"
            assert row["source"] in ("channels", "departments", "both"), (
                f"Invalid source value: {row['source']!r}"
            )
            assert row["consistency"] in ("ok", "mismatch"), (
                f"Invalid consistency value: {row['consistency']!r}"
            )

    def test_stderr_warning_on_mismatch(self, tmp_path: Path) -> None:
        """Mismatch alias → stderr WARNING line, exit 0 (FR-015)."""
        tokens_dir = tmp_path / "tokens"
        tokens_dir.mkdir()
        _write_channels_json(tokens_dir, "nursing", "UCchannels001")
        _write_departments_json(tokens_dir, [
            {
                "alias": "nursing",
                "display_name": "간호학과",
                "channel_id_env": "TUBE_SCOUT_CHANNEL_ID_NURSING",
                "client_secret_env": "TUBE_SCOUT_CLIENT_SECRET_NURSING",
                "api_key_env": "TUBE_SCOUT_API_KEY_NURSING",
                "registered_at": "2026-01-01T00:00:00Z",
            }
        ])

        import os
        env = {
            "TUBE_SCOUT_TOKENS_DIR": str(tokens_dir),
            "TUBE_SCOUT_CHANNEL_ID_NURSING": "UCdepts_different_999",
        }

        result = _run(["admin", "list", "--json"], env=env)

        assert result.returncode == 0, (
            f"admin list must exit 0 even with mismatch.\n"
            f"stdout:{result.stdout}\nstderr:{result.stderr}"
        )
        assert "WARNING" in result.stderr, (
            f"stderr must contain WARNING for mismatch. Got: {result.stderr!r}"
        )
        assert "nursing" in result.stderr, (
            f"WARNING must mention alias 'nursing'. Got: {result.stderr!r}"
        )
        rows = json.loads(result.stdout)
        nursing_row = next(r for r in rows if r["alias"] == "nursing")
        assert nursing_row["consistency"] == "mismatch", (
            f"nursing consistency must be 'mismatch', got {nursing_row['consistency']!r}"
        )

    def test_both_source_when_alias_in_both_registries(self, tmp_path: Path) -> None:
        """Alias in both registries → source='both' (FR-014)."""
        tokens_dir = tmp_path / "tokens"
        tokens_dir.mkdir()
        _write_channels_json(tokens_dir, "nursing", "UCnursing001")
        _write_departments_json(tokens_dir, [
            {
                "alias": "nursing",
                "display_name": "간호학과",
                "channel_id_env": "TUBE_SCOUT_CHANNEL_ID_NURSING",
                "client_secret_env": "TUBE_SCOUT_CLIENT_SECRET_NURSING",
                "api_key_env": "TUBE_SCOUT_API_KEY_NURSING",
                "registered_at": "2026-01-01T00:00:00Z",
            }
        ])

        import os
        env = {
            "TUBE_SCOUT_TOKENS_DIR": str(tokens_dir),
            "TUBE_SCOUT_CHANNEL_ID_NURSING": "UCnursing001",  # same → ok
        }

        result = _run(["admin", "list", "--json"], env=env)

        assert result.returncode == 0
        rows = json.loads(result.stdout)
        nursing_row = next(r for r in rows if r["alias"] == "nursing")
        assert nursing_row["source"] == "both", (
            f"source must be 'both' for alias in both registries. Got {nursing_row['source']!r}"
        )
        assert nursing_row["consistency"] == "ok", (
            f"consistency must be 'ok' when channel_ids match. Got {nursing_row['consistency']!r}"
        )
