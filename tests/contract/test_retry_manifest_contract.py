"""Contract tests for retry_pending.json schema — T023 (spec 017 US3).

Validates that the JSON written by save_manifest matches the contract schema:
schema_version=2, alias, updated_at (ISO 8601 tz-aware), entries[].
Each entry field set + Literal constraints + timezone-aware ISO 8601.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

KST = timezone(timedelta(hours=9))
NOW_KST = datetime(2026, 5, 16, 17, 43, 42, tzinfo=KST)


def _make_manifest(alias: str = "nursing", entries=None):
    from tube_scout.services.retry_manifest import RetryManifest

    return RetryManifest(
        schema_version=2,
        alias=alias,
        updated_at=NOW_KST,
        entries=entries or [],
    )


def _make_entry(video_id: str = "abc123def45"):
    from tube_scout.models.content import RetryManifestEntry

    return RetryManifestEntry(
        video_id=video_id,
        mp4_filename=None,
        title="1주차 1차시 (간호학과)",
        failed_stage="asr",
        failure_reason="model_loading_failed",
        last_attempt_at=NOW_KST,
        attempt_count=1,
    )


# T023-1: top-level 필드 schema_version == 2
def test_contract_schema_version_is_2(tmp_path: Path) -> None:
    from tube_scout.services.retry_manifest import save_manifest

    path = tmp_path / "retry_pending.json"
    save_manifest(path, _make_manifest())

    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["schema_version"] == 2, "schema_version must be integer 2"


# T023-2: alias 필드 존재 및 non-empty string
def test_contract_alias_field_present_and_nonempty(tmp_path: Path) -> None:
    from tube_scout.services.retry_manifest import save_manifest

    path = tmp_path / "retry_pending.json"
    save_manifest(path, _make_manifest(alias="nursing"))

    data = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(data["alias"], str)
    assert len(data["alias"]) > 0


# T023-3: updated_at 는 ISO 8601 timezone-aware string
def test_contract_updated_at_is_iso8601_tz_aware(tmp_path: Path) -> None:
    from tube_scout.services.retry_manifest import save_manifest

    path = tmp_path / "retry_pending.json"
    save_manifest(path, _make_manifest())

    data = json.loads(path.read_text(encoding="utf-8"))
    updated_at_str = data["updated_at"]
    parsed = datetime.fromisoformat(updated_at_str)
    assert parsed.tzinfo is not None, "updated_at must be timezone-aware"


# T023-4: entries 는 array
def test_contract_entries_is_array(tmp_path: Path) -> None:
    from tube_scout.services.retry_manifest import save_manifest

    path = tmp_path / "retry_pending.json"
    save_manifest(path, _make_manifest())

    data = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(data["entries"], list)


# T023-5: entry 필드 셋 완전 일치 (v2: mp4_filename 추가)
def test_contract_entry_field_set_complete(tmp_path: Path) -> None:
    from tube_scout.services.retry_manifest import save_manifest

    path = tmp_path / "retry_pending.json"
    entry = _make_entry()
    save_manifest(path, _make_manifest(entries=[entry]))

    data = json.loads(path.read_text(encoding="utf-8"))
    assert len(data["entries"]) == 1
    row = data["entries"][0]
    required = {"video_id", "mp4_filename", "title", "failed_stage", "failure_reason", "last_attempt_at", "attempt_count"}
    assert required == set(row.keys()), f"Entry fields mismatch: {set(row.keys())}"


# T023-6: failed_stage Literal 제약 (v2 enum)
_VALID_STAGES = {"asr", "fingerprint", "audio_decode", "aborted_by_user", "ingest_mapping", "ingest_no_mp4"}


def test_contract_entry_failed_stage_is_literal(tmp_path: Path) -> None:
    from tube_scout.services.retry_manifest import save_manifest

    path = tmp_path / "retry_pending.json"
    entry = _make_entry()
    save_manifest(path, _make_manifest(entries=[entry]))

    data = json.loads(path.read_text(encoding="utf-8"))
    row = data["entries"][0]
    assert row["failed_stage"] in _VALID_STAGES, (
        f"failed_stage must be one of {_VALID_STAGES}, got {row['failed_stage']!r}"
    )


# T023-7: attempt_count >= 1
def test_contract_entry_attempt_count_ge_1(tmp_path: Path) -> None:
    from tube_scout.services.retry_manifest import save_manifest

    path = tmp_path / "retry_pending.json"
    entry = _make_entry()
    save_manifest(path, _make_manifest(entries=[entry]))

    data = json.loads(path.read_text(encoding="utf-8"))
    row = data["entries"][0]
    assert isinstance(row["attempt_count"], int)
    assert row["attempt_count"] >= 1


# T023-8: last_attempt_at 는 ISO 8601 timezone-aware
def test_contract_entry_last_attempt_at_is_iso8601_tz_aware(tmp_path: Path) -> None:
    from tube_scout.services.retry_manifest import save_manifest

    path = tmp_path / "retry_pending.json"
    entry = _make_entry()
    save_manifest(path, _make_manifest(entries=[entry]))

    data = json.loads(path.read_text(encoding="utf-8"))
    row = data["entries"][0]
    parsed = datetime.fromisoformat(row["last_attempt_at"])
    assert parsed.tzinfo is not None, "last_attempt_at must be timezone-aware"


# T023-9: video_id non-empty string (when present)
def test_contract_entry_video_id_nonempty(tmp_path: Path) -> None:
    from tube_scout.services.retry_manifest import save_manifest

    path = tmp_path / "retry_pending.json"
    entry = _make_entry("abc123def45")
    save_manifest(path, _make_manifest(entries=[entry]))

    data = json.loads(path.read_text(encoding="utf-8"))
    row = data["entries"][0]
    assert row["video_id"] is None or (isinstance(row["video_id"], str) and len(row["video_id"]) > 0)
