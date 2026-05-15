"""T034~T036 RED — admin list union + consistency tests (spec 016 US2).

Covers:
  T034 (FR-014): channels.json + departments.json union → 2 rows + correct source
  T035 (FR-015): same alias, different channel_id → consistency=mismatch + stderr WARNING
  T036 (FR-015 후반부): mismatch alias in collect command → exit 1
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path


def _run(args: list[str], env: dict | None = None) -> subprocess.CompletedProcess:
    import os
    import shutil
    full_env = os.environ.copy()
    if env:
        full_env.update(env)
    bin_ = shutil.which("tube-scout") or "tube-scout"
    return subprocess.run([bin_, *args], capture_output=True, text=True, env=full_env)


def _write_channels_json(tokens_dir: Path, entries: list[dict]) -> None:
    data = {e["alias"]: e for e in entries}
    (tokens_dir / "channels.json").write_text(
        json.dumps(data), encoding="utf-8"
    )


def _write_departments_json(tokens_dir: Path, entries: list[dict]) -> None:
    (tokens_dir / "departments.json").write_text(
        json.dumps(entries), encoding="utf-8"
    )


class TestAdminListUnion:
    """T034 — admin list shows union of both registries (FR-014)."""

    def test_union_of_two_registries(self, tmp_path: Path) -> None:
        """channels.json=nursing, departments.json=nursing2 → 2 rows + source columns."""
        tokens_dir = tmp_path / "tokens"
        tokens_dir.mkdir()

        _write_channels_json(tokens_dir, [
            {
                "alias": "nursing",
                "channel_id": "UCnurse001",
                "channel_name": "간호학과",
                "registered_at": "2026-01-01T00:00:00Z",
                "last_used_at": "2026-01-01T00:00:00Z",
                "token_path": str(tokens_dir / "nursing_token.json"),
            }
        ])
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
            f"admin list must exit 0.\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )
        rows = json.loads(result.stdout)
        aliases = {r["alias"] for r in rows}
        assert "nursing" in aliases, "nursing (channels.json) must appear in union"
        assert "nursing2" in aliases, "nursing2 (departments.json) must appear in union"

        nursing_row = next(r for r in rows if r["alias"] == "nursing")
        nursing2_row = next(r for r in rows if r["alias"] == "nursing2")
        assert nursing_row["source"] == "channels", (
            f"nursing source must be 'channels', got {nursing_row['source']!r}"
        )
        assert nursing2_row["source"] == "departments", (
            f"nursing2 source must be 'departments', got {nursing2_row['source']!r}"
        )


class TestAdminListConsistency:
    """T035 — mismatch detection with WARNING + consistency field (FR-015)."""

    def test_mismatch_displays_warning_and_consistency(self, tmp_path: Path) -> None:
        """Same alias in both registries with different channel_id → mismatch + WARNING."""
        tokens_dir = tmp_path / "tokens"
        tokens_dir.mkdir()

        _write_channels_json(tokens_dir, [
            {
                "alias": "nursing",
                "channel_id": "UCnurse_channels_001",
                "channel_name": "간호학과",
                "registered_at": "2026-01-01T00:00:00Z",
                "last_used_at": "2026-01-01T00:00:00Z",
                "token_path": str(tokens_dir / "nursing_token.json"),
            }
        ])
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

        env = {
            "TUBE_SCOUT_TOKENS_DIR": str(tokens_dir),
            # channel_id_env points to a different value → mismatch
            "TUBE_SCOUT_CHANNEL_ID_NURSING": "UCnurse_departments_999",
        }

        result = _run(["admin", "list", "--json"], env=env)

        assert result.returncode == 0, (
            f"admin list must exit 0 even with mismatch.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
        rows = json.loads(result.stdout)
        nursing_row = next(r for r in rows if r["alias"] == "nursing")
        assert nursing_row.get("consistency") == "mismatch", (
            f"consistency must be 'mismatch', got {nursing_row.get('consistency')!r}"
        )
        assert "WARNING" in result.stderr and "nursing" in result.stderr, (
            f"stderr must contain WARNING for mismatch alias. Got: {result.stderr!r}"
        )


class TestAdminListBlockingAnalysis:
    """T036 — mismatch alias blocks collect/analyze/report commands (FR-015 후반부)."""

    def test_mismatch_blocks_collect_command(self, tmp_path: Path) -> None:
        """collect takeout with mismatch alias → exit 1 with mismatch in error (FR-015 후반부).

        The test verifies that the mismatch check is performed BEFORE any
        filesystem validation, so that the blocking message is about channel_id
        inconsistency, not about a missing takeout directory.
        """
        tokens_dir = tmp_path / "tokens"
        tokens_dir.mkdir()

        _write_channels_json(tokens_dir, [
            {
                "alias": "nursing",
                "channel_id": "UCnurse_channels_001",
                "channel_name": "간호학과",
                "registered_at": "2026-01-01T00:00:00Z",
                "last_used_at": "2026-01-01T00:00:00Z",
                "token_path": str(tokens_dir / "nursing_token.json"),
            }
        ])
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

        # Build a valid takeout dir so that the only failure can be the mismatch check
        yt_dir = tmp_path / "Takeout" / "YouTube 및 YouTube Music"
        meta_dir = yt_dir / "동영상 메타데이터"
        channel_dir = yt_dir / "채널"
        meta_dir.mkdir(parents=True)
        channel_dir.mkdir(parents=True)
        import csv as _csv
        with (channel_dir / "채널.csv").open("w", encoding="utf-8", newline="") as f:
            w = _csv.writer(f)
            w.writerow(["채널 ID", "채널 국가", "채널 태그 1", "채널 제목(원본)", "채널 공개 상태"])
            w.writerow(["UCnurse_channels_001", "KR", "태그", "간호학과", "공개"])
        with (meta_dir / "동영상.csv").open("w", encoding="utf-8", newline="") as f:
            w = _csv.writer(f)
            w.writerow([
                "동영상 ID", "근사치 길이(밀리초)", "동영상 오디오 언어", "동영상 카테고리",
                "동영상 설명(원본) 언어", "채널 ID", "동영상 제목(원본)", "동영상 제목(원본) 언어",
                "개인 정보 보호", "동영상 상태", "동영상 생성 타임스탬프",
            ])
            w.writerow(["vid001", "60000", "ko", "교육", "ko",
                        "UCnurse_channels_001", "제목", "ko", "비공개",
                        "처리됨", "2026-01-01T00:00:00+00:00"])

        env = {
            "TUBE_SCOUT_TOKENS_DIR": str(tokens_dir),
            # Different channel_id → mismatch
            "TUBE_SCOUT_CHANNEL_ID_NURSING": "UCnurse_departments_999",
        }

        result = _run(
            [
                "collect", "takeout",
                "--takeout-dir", str(tmp_path),
                "--channel", "nursing",
            ],
            env=env,
        )

        assert result.returncode == 1, (
            f"collect with mismatch alias must exit 1.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
        combined = result.stdout + result.stderr
        assert "mismatch" in combined.lower() or "inconsisten" in combined.lower(), (
            f"Error must mention mismatch/inconsistency. Got: {combined!r}"
        )
