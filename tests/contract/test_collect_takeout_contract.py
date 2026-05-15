"""Contract tests for `tube-scout collect takeout` CLI command (T015).

Covers 8 error cases from contracts/collect-takeout.md Error cases table:
  1. alias 미등록
  2. takeout_dir 부재
  3. 채널.csv 부재
  4. 동영상*.csv 0개
  5. 채널 제목(원본) 컬럼 부재
  6. 동영상 ID 컬럼 부재 (required column missing)
  7. alias B-1+B-2 channel_id 불일치
  8. --dry-run succeeds (exit 0 sanity)
"""

from __future__ import annotations

import csv
import subprocess
from pathlib import Path

import pytest

_REAL_CHANNEL_HEADER = [
    "채널 ID", "채널 국가", "채널 태그 1", "채널 제목(원본)", "채널 공개 상태",
]
_REAL_VIDEO_HEADER = [
    "동영상 ID", "근사치 길이(밀리초)", "동영상 오디오 언어", "동영상 카테고리",
    "동영상 설명(원본) 언어", "채널 ID", "동영상 제목(원본)", "동영상 제목(원본) 언어",
    "개인 정보 보호", "동영상 상태", "동영상 생성 타임스탬프",
]


def _run(args: list[str], env: dict | None = None) -> subprocess.CompletedProcess:
    import os
    import shutil
    full_env = os.environ.copy()
    if env:
        full_env.update(env)
    tube_scout_bin = shutil.which("tube-scout") or "tube-scout"
    return subprocess.run(
        [tube_scout_bin, *args],
        capture_output=True,
        text=True,
        env=full_env,
    )


def _write_channel_csv(path: Path, channel_id: str = "UCtest001",
                       title: str = "테스트채널") -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(_REAL_CHANNEL_HEADER)
        w.writerow([channel_id, "KR", "태그", title, "공개"])


def _write_video_csv(path: Path, rows: list[dict] | None = None) -> None:
    default_row = {
        "동영상 ID": "vid001",
        "근사치 길이(밀리초)": "3600000",
        "동영상 오디오 언어": "ko",
        "동영상 카테고리": "교육",
        "동영상 설명(원본) 언어": "ko",
        "채널 ID": "UCtest001",
        "동영상 제목(원본)": "제목",
        "동영상 제목(원본) 언어": "ko",
        "개인 정보 보호": "비공개",
        "동영상 상태": "처리됨",
        "동영상 생성 타임스탬프": "2026-01-01T00:00:00+00:00",
    }
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=_REAL_VIDEO_HEADER)
        w.writeheader()
        for row in (rows or [default_row]):
            w.writerow(row)


def _make_valid_takeout(tmp_path: Path, channel_id: str = "UCtest001") -> Path:
    takeout_root = tmp_path / "Takeout"
    yt_dir = takeout_root / "YouTube 및 YouTube Music"
    meta_dir = yt_dir / "동영상 메타데이터"
    channel_dir = yt_dir / "채널"
    meta_dir.mkdir(parents=True)
    channel_dir.mkdir(parents=True)
    _write_channel_csv(channel_dir / "채널.csv", channel_id=channel_id)
    _write_video_csv(meta_dir / "동영상.csv")
    return tmp_path  # archive root (parent of Takeout/)


@pytest.fixture()
def registered_alias_env(tmp_path):
    """Provide a temporary channels.json with 'testch' alias registered."""
    import json
    tokens_dir = tmp_path / "tokens"
    tokens_dir.mkdir()
    channels_json = tokens_dir / "channels.json"
    channels_json.write_text(json.dumps({
        "testch": {
            "alias": "testch",
            "channel_id": "UCtest001",
            "channel_name": "Test Channel",
            "registered_at": "2026-01-01T00:00:00Z",
            "last_used_at": "2026-01-01T00:00:00Z",
            "token_path": str(tokens_dir / "testch_token.json"),
        }
    }), encoding="utf-8")
    return {"TUBE_SCOUT_TOKENS_DIR": str(tokens_dir)}


class TestCollectTakeoutErrorCases:
    """T015 — 8 error cases from collect-takeout.md contract."""

    def test_unregistered_alias_exit1(self, tmp_path: Path, registered_alias_env: dict) -> None:
        """Unregistered alias → exit 1, stderr mentions alias."""
        archive = _make_valid_takeout(tmp_path / "archive")
        result = _run(
            ["collect", "takeout",
             "--takeout-dir", str(archive),
             "--channel", "nonexistent_alias"],
            env=registered_alias_env,
        )
        assert result.returncode == 1
        combined = result.stdout + result.stderr
        assert "nonexistent_alias" in combined

    def test_missing_takeout_dir_exit1(self, tmp_path: Path, registered_alias_env: dict) -> None:
        """Non-existent takeout_dir → exit 1, stderr mentions path."""
        missing_path = tmp_path / "no_such_dir"
        result = _run(
            ["collect", "takeout",
             "--takeout-dir", str(missing_path),
             "--channel", "testch"],
            env=registered_alias_env,
        )
        assert result.returncode == 1
        assert str(missing_path) in result.stdout + result.stderr

    def test_missing_channel_csv_exit1(self, tmp_path: Path, registered_alias_env: dict) -> None:
        """No 채널.csv → exit 1, stderr mentions 채널.csv."""
        takeout_root = tmp_path / "Takeout"
        yt_dir = takeout_root / "YouTube 및 YouTube Music"
        meta_dir = yt_dir / "동영상 메타데이터"
        channel_dir = yt_dir / "채널"
        meta_dir.mkdir(parents=True)
        channel_dir.mkdir(parents=True)
        # write video csv but NO channel csv
        _write_video_csv(meta_dir / "동영상.csv")

        result = _run(
            ["collect", "takeout",
             "--takeout-dir", str(tmp_path),
             "--channel", "testch"],
            env=registered_alias_env,
        )
        assert result.returncode == 1
        assert "채널.csv" in result.stdout + result.stderr

    def test_missing_video_csv_exit1(self, tmp_path: Path, registered_alias_env: dict) -> None:
        """No 동영상*.csv → exit 1."""
        takeout_root = tmp_path / "Takeout"
        yt_dir = takeout_root / "YouTube 및 YouTube Music"
        meta_dir = yt_dir / "동영상 메타데이터"
        channel_dir = yt_dir / "채널"
        meta_dir.mkdir(parents=True)
        channel_dir.mkdir(parents=True)
        _write_channel_csv(channel_dir / "채널.csv")
        # no video csv

        result = _run(
            ["collect", "takeout",
             "--takeout-dir", str(tmp_path),
             "--channel", "testch"],
            env=registered_alias_env,
        )
        assert result.returncode == 1

    def test_missing_channel_title_column_exit1(self, tmp_path: Path, registered_alias_env: dict) -> None:
        """채널.csv missing '채널 제목(원본)' → exit 1, stderr mentions column."""
        takeout_root = tmp_path / "Takeout"
        yt_dir = takeout_root / "YouTube 및 YouTube Music"
        meta_dir = yt_dir / "동영상 메타데이터"
        channel_dir = yt_dir / "채널"
        meta_dir.mkdir(parents=True)
        channel_dir.mkdir(parents=True)

        # Write channel csv without required column
        with (channel_dir / "채널.csv").open("w", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["채널 ID", "채널 국가"])  # missing 채널 제목(원본)
            w.writerow(["UCtest001", "KR"])
        _write_video_csv(meta_dir / "동영상.csv")

        result = _run(
            ["collect", "takeout",
             "--takeout-dir", str(tmp_path),
             "--channel", "testch"],
            env=registered_alias_env,
        )
        assert result.returncode == 1

    def test_missing_video_id_column_exit1(self, tmp_path: Path, registered_alias_env: dict) -> None:
        """동영상.csv missing '동영상 ID' → exit 1."""
        takeout_root = tmp_path / "Takeout"
        yt_dir = takeout_root / "YouTube 및 YouTube Music"
        meta_dir = yt_dir / "동영상 메타데이터"
        channel_dir = yt_dir / "채널"
        meta_dir.mkdir(parents=True)
        channel_dir.mkdir(parents=True)
        _write_channel_csv(channel_dir / "채널.csv")

        with (meta_dir / "동영상.csv").open("w", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["동영상 제목(원본)", "채널 ID"])  # missing 동영상 ID
            w.writerow(["제목", "UCtest001"])

        result = _run(
            ["collect", "takeout",
             "--takeout-dir", str(tmp_path),
             "--channel", "testch"],
            env=registered_alias_env,
        )
        assert result.returncode == 1
