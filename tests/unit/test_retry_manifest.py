"""Unit tests for services/retry_manifest.py — T021 Acceptance Matrix 9 cases (spec 017 US3)."""

from __future__ import annotations

import os
import stat
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest

NOW = datetime(2026, 5, 16, 8, 43, 42, tzinfo=UTC)


def _make_entry(video_id: str = "abc123def45", attempt_count: int = 1):
    from tube_scout.models.content import RetryManifestEntry

    return RetryManifestEntry(
        video_id=video_id,
        title="1주차 1차시",
        failed_stage="transcript",
        failure_reason="model_loading_failed",
        last_attempt_at=NOW,
        attempt_count=attempt_count,
    )


def _make_failure(video_id: str = "abc123def45"):
    from tube_scout.models.content import FailureEntry

    return FailureEntry(
        video_id=video_id,
        title="1주차 1차시",
        failed_stage="transcript",
        failure_reason="model_loading_failed",
        attempted_at=NOW,
    )


# T021-1: 빈 매니페스트 로드 (파일 부재)
def test_load_manifest_missing_file_returns_empty(tmp_path: Path) -> None:
    from tube_scout.services.retry_manifest import load_manifest

    manifest = load_manifest(tmp_path / "retry_pending.json")
    assert manifest.entries == []
    assert manifest.schema_version == 1


# T021-2: 단일 실패 추가
def test_add_or_update_failures_single_entry(tmp_path: Path) -> None:
    from tube_scout.services.retry_manifest import RetryManifest, add_or_update_failures

    manifest = RetryManifest(schema_version=1, alias="nursing", updated_at=NOW, entries=[])
    failure = _make_failure("vid001")
    delta = add_or_update_failures(manifest, [failure], now=NOW)

    assert len(manifest.entries) == 1
    assert manifest.entries[0].video_id == "vid001"
    assert manifest.entries[0].attempt_count == 1
    assert delta.added_count == 1
    assert delta.resolved_count == 0
    assert delta.remaining_count == 1


# T021-3: 같은 영상 재실패 → attempt_count 증가
def test_add_or_update_failures_increments_attempt_count(tmp_path: Path) -> None:
    from tube_scout.services.retry_manifest import RetryManifest, add_or_update_failures

    entry = _make_entry("vid002", attempt_count=1)
    manifest = RetryManifest(schema_version=1, alias="nursing", updated_at=NOW, entries=[entry])

    later = datetime(2026, 5, 16, 9, 0, 0, tzinfo=UTC)
    failure = _make_failure("vid002")
    delta = add_or_update_failures(manifest, [failure], now=later)

    assert len(manifest.entries) == 1
    assert manifest.entries[0].attempt_count == 2
    assert manifest.entries[0].last_attempt_at == later
    assert delta.added_count == 0
    assert delta.remaining_count == 1


# T021-4: 성공 해소 → entries 제거
def test_resolve_successes_removes_entry(tmp_path: Path) -> None:
    from tube_scout.services.retry_manifest import RetryManifest, resolve_successes

    entry = _make_entry("vid003")
    manifest = RetryManifest(schema_version=1, alias="nursing", updated_at=NOW, entries=[entry])

    delta = resolve_successes(manifest, {"vid003"})

    assert len(manifest.entries) == 0
    assert delta.resolved_count == 1
    assert delta.added_count == 0
    assert delta.remaining_count == 0


# T021-5: schema_version 불일치 → ValueError
def test_load_manifest_schema_version_mismatch_raises(tmp_path: Path) -> None:
    from tube_scout.services.retry_manifest import load_manifest

    path = tmp_path / "retry_pending.json"
    path.write_text(
        '{"schema_version": 99, "alias": "nursing", "updated_at": "2026-05-16T08:43:42+00:00", "entries": []}',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="schema_version"):
        load_manifest(path)


# T021-6: alias 불일치 → ValueError
def test_load_manifest_alias_mismatch_raises(tmp_path: Path) -> None:
    from tube_scout.services.retry_manifest import (
        RetryManifest,
        load_manifest,
        save_manifest,
    )

    manifest = RetryManifest(schema_version=1, alias="nursing", updated_at=NOW, entries=[])
    path = tmp_path / "retry_pending.json"
    save_manifest(path, manifest)

    with pytest.raises(ValueError, match="alias"):
        load_manifest(path, expected_alias="pharmacy")


# T021-7: atomic write 부분 실패 → 기존 파일 보존
def test_save_manifest_partial_write_preserves_existing(tmp_path: Path) -> None:
    from tube_scout.services.retry_manifest import (
        RetryManifest,
        save_manifest,
    )

    path = tmp_path / "retry_pending.json"
    original = RetryManifest(schema_version=1, alias="nursing", updated_at=NOW, entries=[_make_entry()])
    save_manifest(path, original)
    original_text = path.read_text(encoding="utf-8")

    new_manifest = RetryManifest(schema_version=1, alias="nursing", updated_at=NOW, entries=[])

    with patch("os.replace", side_effect=OSError("disk full")):
        with pytest.raises(OSError):
            save_manifest(path, new_manifest)

    assert path.read_text(encoding="utf-8") == original_text


# T021-8: max_attempts 초과 entry 는 select_retry_targets 에서 제외
def test_select_retry_targets_excludes_max_attempts_exceeded(tmp_path: Path) -> None:
    from tube_scout.services.retry_manifest import RetryManifest, select_retry_targets

    under = _make_entry("vid_under", attempt_count=4)
    at_max = _make_entry("vid_max", attempt_count=5)
    manifest = RetryManifest(schema_version=1, alias="nursing", updated_at=NOW, entries=[under, at_max])

    targets = select_retry_targets(manifest, max_attempts=5)

    assert "vid_under" in targets
    assert "vid_max" not in targets


# T021-9: 0600 권한 보장
def test_save_manifest_sets_0600_permission(tmp_path: Path) -> None:
    from tube_scout.services.retry_manifest import RetryManifest, save_manifest

    path = tmp_path / "retry_pending.json"
    manifest = RetryManifest(schema_version=1, alias="nursing", updated_at=NOW, entries=[])
    save_manifest(path, manifest)

    mode = stat.S_IMODE(os.stat(path).st_mode)
    assert mode == 0o600, f"Expected 0o600, got {oct(mode)}"
