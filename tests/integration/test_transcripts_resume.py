"""Spec 010 — Integration tests for skip-existing resume on `collect transcripts`."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from tube_scout.cli.main import app
from tube_scout.storage.json_store import write_json

runner = CliRunner()


def _make_data_dir(tmp_path: Path) -> Path:
    """Create a minimal valid data dir with config + auth glue."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "checkpoints").mkdir()
    write_json(
        data_dir / "config.json",
        {
            "channels": [
                {
                    "channel_id": "UCxxxxxxxxxxxxxxxxxxxxxx",
                    "professor_name": "홍길동",
                }
            ],
            "settings": {
                "data_dir": str(data_dir),
                "sentiment_backend": "llm",
                "default_report_format": "html",
                "rate_limit_transcript": {
                    "base_delay": 0.0,
                    "max_retries": 0,
                    "backoff_multiplier": 1.0,
                    "jitter": 0.0,
                },
            },
        },
    )
    return data_dir


def _make_project_with_videos(tmp_path: Path, video_ids: list[str]) -> Path:
    """Create a project dir with videos_meta.json listing the given video IDs."""
    project_root = tmp_path / "projects"
    project_root.mkdir()
    proj = project_root / "test_run"
    channel_id = "UCxxxxxxxxxxxxxxxxxxxxxx"
    coll = proj / "01_collect" / "channels" / channel_id
    coll.mkdir(parents=True)
    write_json(
        coll / "videos_meta.json",
        [
            {
                "video_id": vid,
                "title": f"Sample Lecture {vid}",
                "published_at": "2026-04-06T07:24:13Z",
                "channel_id": channel_id,
                "privacy_status": "unlisted",
            }
            for vid in video_ids
        ],
    )
    return project_root


def _seed_cached_transcript(
    project_dir: Path, vid_id: str, segments: list[dict] | None = None
) -> Path:
    """Drop a valid cached transcript JSON for `vid_id`."""
    cache_dir = project_dir / "test_run" / "01_collect" / "transcripts"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache = cache_dir / f"{vid_id}.json"
    payload = {
        "video_id": vid_id,
        "transcript_type": "manual",
        "source": "manual",
        "segments": segments
        if segments is not None
        else [{"text": "cached", "start": 0.0, "duration": 1.0}],
    }
    cache.write_text(json.dumps(payload), encoding="utf-8")
    return cache


def _read_audit_csv(project_dir: Path) -> list[dict[str, str]]:
    audit = project_dir / "test_run" / "01_collect" / "transcripts_audit.csv"
    if not audit.exists():
        return []
    with audit.open("r", encoding="utf-8") as f:
        return list(csv.DictReader(f))


@pytest.fixture
def patched_runner(monkeypatch: pytest.MonkeyPatch):
    """Patches that bypass real auth + Captions API setup so we can drive the CLI."""
    fake_creds = MagicMock()
    fake_yt = MagicMock()
    fake_caps = MagicMock()
    fake_caps.fetch_segments.return_value = None  # no captions for missing videos

    with (
        patch("tube_scout.services.auth.authenticate_channel", return_value=fake_creds),
        patch("tube_scout.services.auth._authorized_http", return_value=MagicMock()),
        patch(
            "googleapiclient.discovery.build",
            return_value=fake_yt,
        ),
        patch(
            "tube_scout.services.captions_api.CaptionsAPIClient",
            return_value=fake_caps,
        ),
    ):
        yield


class TestPartialThenResume:
    """FR-010-04 / US2 acceptance scenario 1: 5 videos, 3 cached, only 2 fetched."""

    def test_three_of_five_cached_two_fetched(
        self, tmp_path: Path, patched_runner
    ) -> None:
        data_dir = _make_data_dir(tmp_path)
        video_ids = ["vid_a", "vid_b", "vid_c", "vid_d", "vid_e"]
        proj_root = _make_project_with_videos(tmp_path, video_ids)
        for cached in ("vid_a", "vid_b", "vid_c"):
            _seed_cached_transcript(proj_root, cached)

        # Mock TranscriptService.fetch_transcript to count calls and produce data.
        with patch(
            "tube_scout.services.transcript.TranscriptService"
        ) as mock_service_cls:
            mock_service = MagicMock()
            mock_service.fetch_transcript.return_value = {
                "video_id": "fetched",
                "transcript_type": "manual",
                "source": "manual",
                "segments": [{"text": "x", "start": 0.0, "duration": 1.0}],
            }
            mock_service_cls.return_value = mock_service

            # Pre-register channel registry so resolve_channel_alias passes
            # (autouse fixture already provides "nursing" alias).
            result = runner.invoke(
                app,
                [
                    "collect",
                    "transcripts",
                    "--data-dir",
                    str(data_dir),
                    "--project-dir",
                    str(proj_root),
                    "--project",
                    str(proj_root / "test_run"),
                    "--channel",
                    "nursing",
                ],
            )

        # Expect exactly 2 fetches: vid_d, vid_e.
        assert mock_service.fetch_transcript.call_count == 2, (
            f"expected 2 fetches (uncached), got {mock_service.fetch_transcript.call_count}\n"
            f"output: {result.output[:500]}"
        )

        # Audit CSV: 3 skipped rows (vid_a, vid_b, vid_c).
        rows = _read_audit_csv(proj_root)
        skipped = [r for r in rows if r["classification"] == "skipped"]
        assert len(skipped) == 3
        skipped_ids = {r["video_id"] for r in skipped}
        assert skipped_ids == {"vid_a", "vid_b", "vid_c"}


class TestForceRefreshOverridesCache:
    """FR-010-05: --force-refresh re-fetches every video; no skipped rows emitted."""

    def test_force_refresh_refetches_all(
        self, tmp_path: Path, patched_runner
    ) -> None:
        data_dir = _make_data_dir(tmp_path)
        video_ids = ["vid_a", "vid_b", "vid_c"]
        proj_root = _make_project_with_videos(tmp_path, video_ids)
        for cached in video_ids:
            _seed_cached_transcript(proj_root, cached)

        with patch(
            "tube_scout.services.transcript.TranscriptService"
        ) as mock_service_cls:
            mock_service = MagicMock()
            mock_service.fetch_transcript.return_value = {
                "video_id": "x",
                "transcript_type": "manual",
                "source": "manual",
                "segments": [{"text": "fresh", "start": 0.0, "duration": 1.0}],
            }
            mock_service_cls.return_value = mock_service

            runner.invoke(
                app,
                [
                    "collect",
                    "transcripts",
                    "--data-dir",
                    str(data_dir),
                    "--project-dir",
                    str(proj_root),
                    "--project",
                    str(proj_root / "test_run"),
                    "--channel",
                    "nursing",
                    "--force-refresh",
                ],
            )

        assert mock_service.fetch_transcript.call_count == 3

        rows = _read_audit_csv(proj_root)
        skipped = [r for r in rows if r["classification"] == "skipped"]
        assert len(skipped) == 0


class TestCorruptCacheRefetches:
    """EC-010-A: corrupt cache JSON treated as missing; re-fetched."""

    def test_corrupt_cache_refetched(self, tmp_path: Path, patched_runner) -> None:
        data_dir = _make_data_dir(tmp_path)
        video_ids = ["vid_a", "vid_b"]
        proj_root = _make_project_with_videos(tmp_path, video_ids)

        # Seed vid_a with valid cache, vid_b with truncated/corrupt JSON.
        _seed_cached_transcript(proj_root, "vid_a")
        bad_path = (
            proj_root / "test_run" / "01_collect" / "transcripts" / "vid_b.json"
        )
        bad_path.write_text("{not valid json", encoding="utf-8")

        with patch(
            "tube_scout.services.transcript.TranscriptService"
        ) as mock_service_cls:
            mock_service = MagicMock()
            mock_service.fetch_transcript.return_value = {
                "video_id": "vid_b",
                "transcript_type": "manual",
                "source": "manual",
                "segments": [{"text": "fresh", "start": 0.0, "duration": 1.0}],
            }
            mock_service_cls.return_value = mock_service

            runner.invoke(
                app,
                [
                    "collect",
                    "transcripts",
                    "--data-dir",
                    str(data_dir),
                    "--project-dir",
                    str(proj_root),
                    "--project",
                    str(proj_root / "test_run"),
                    "--channel",
                    "nursing",
                ],
            )

        # vid_a skipped (valid cache), vid_b re-fetched (corrupt cache).
        assert mock_service.fetch_transcript.call_count == 1
        # Corrupt file is overwritten with valid JSON.
        loaded = json.loads(bad_path.read_text(encoding="utf-8"))
        assert "segments" in loaded


class TestEmptySegmentsRefetches:
    """EC-010-C: cached file with `segments=[]` treated as missing."""

    def test_empty_segments_refetched(self, tmp_path: Path, patched_runner) -> None:
        data_dir = _make_data_dir(tmp_path)
        video_ids = ["vid_a"]
        proj_root = _make_project_with_videos(tmp_path, video_ids)
        _seed_cached_transcript(proj_root, "vid_a", segments=[])

        with patch(
            "tube_scout.services.transcript.TranscriptService"
        ) as mock_service_cls:
            mock_service = MagicMock()
            mock_service.fetch_transcript.return_value = {
                "video_id": "vid_a",
                "transcript_type": "manual",
                "source": "manual",
                "segments": [{"text": "fresh", "start": 0.0, "duration": 1.0}],
            }
            mock_service_cls.return_value = mock_service

            runner.invoke(
                app,
                [
                    "collect",
                    "transcripts",
                    "--data-dir",
                    str(data_dir),
                    "--project-dir",
                    str(proj_root),
                    "--project",
                    str(proj_root / "test_run"),
                    "--channel",
                    "nursing",
                ],
            )

        # Empty segments cache → re-fetched.
        assert mock_service.fetch_transcript.call_count == 1
