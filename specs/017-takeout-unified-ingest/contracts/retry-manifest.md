# Contract: Retry Manifest (`data/<alias>/retry_pending.json`)

**Spec**: [spec.md](../spec.md) — FR-015, FR-018, SC-008
**Data model**: [data-model.md](../data-model.md) — E-7 RetryManifest, E-6 RetryManifestDelta

본 contract 는 spec 017 이 신규 도입하는 재시도 매니페스트 파일의 schema, 위치, 무결성 보장, 그리고 매니페스트 매니저 함수의 시그니처를 정의한다.

## File Location

```
<data-dir>/<alias>/retry_pending.json
```

기본 `data-dir = ./data`. 따라서 nursing 학과 매니페스트는 `./data/nursing/retry_pending.json`.

boundary B-8 (`data/<alias>/` 디렉토리 규약) 와 일관 — `channel_meta.json`, `videos_meta.json`, `동영상/` symlink 와 같은 위치.

## Schema

```json
{
  "schema_version": 1,
  "alias": "nursing",
  "updated_at": "2026-05-16T08:43:42+09:00",
  "entries": [
    {
      "video_id": "abc123def45",
      "title": "1주차 1차시 (간호학과)",
      "failed_stage": "transcript",
      "failure_reason": "model_loading_failed",
      "last_attempt_at": "2026-05-16T08:43:42+09:00",
      "attempt_count": 1
    }
  ]
}
```

### Top-level Fields

| 필드 | 타입 | 제약 | 의미 |
|---|---|---|---|
| `schema_version` | int | `== 1` | 매니페스트 스키마 버전. 향후 진화 시 migration 트리거 |
| `alias` | str | non-empty, 등록부에 존재 | 학과 alias |
| `updated_at` | str (ISO 8601) | timezone-aware | 마지막 갱신 시각 (KST 권장) |
| `entries` | array | 0 개 이상 | 재시도 대상 영상 row 목록 |

### Entry Fields

| 필드 | 타입 | 제약 | 의미 |
|---|---|---|---|
| `video_id` | str | non-empty, SQLite `video_metadata.video_id` 에 존재 | YouTube video_id |
| `title` | str | non-empty | 영상 제목 (운영자 식별용) |
| `failed_stage` | str | `transcript` \| `fingerprint` | 마지막 실패 단계 |
| `failure_reason` | str | non-empty, 사전 정의 어휘 | 실패 사유 (audit 로그의 `reason` 컬럼과 통일) |
| `last_attempt_at` | str (ISO 8601) | timezone-aware | 마지막 시도 시각 |
| `attempt_count` | int | `>= 1` | 누적 시도 횟수. N 회 초과 시 운영자 수동 점검 신호 |

## Atomic Write

본 매니페스트는 `_write_json_atomic()` 헬퍼 (spec 013 / spec 016 와 동일 패턴) 로 저장된다.

```
tmp_path = path.parent / f".{path.name}.tmp.<random>"
json.dump(data, tmp_file, ensure_ascii=False, indent=2)
fsync(tmp_file)
os.rename(tmp_path, path)
chmod(path, 0o600)
```

부분 쓰기 (partial write) 가 발생해도 기존 매니페스트는 손상되지 않는다.

## Manager Function Signatures

`src/tube_scout/services/retry_manifest.py` 가 본 매니페스트의 lifecycle 을 관리한다. 다른 모듈은 본 매니저를 통해서만 매니페스트를 읽고 쓴다.

### `load_manifest(manifest_path: Path) -> RetryManifest`

매니페스트 파일을 읽어 pydantic 모델로 반환한다. 파일이 부재하면 빈 매니페스트 (entries = []) 를 반환 (Principle II 의 fail-fast 와 충돌하지 않는 합법적 초기 상태).

```python
def load_manifest(manifest_path: Path) -> RetryManifest:
    """Load retry manifest from disk.

    Returns empty manifest (entries=[]) if file is absent. Raises
    ValueError if schema_version mismatch or alias inconsistency
    detected.
    """
```

### `save_manifest(manifest_path: Path, manifest: RetryManifest) -> None`

매니페스트를 atomic write 로 저장한다. 0600 권한.

```python
def save_manifest(manifest_path: Path, manifest: RetryManifest) -> None:
    """Persist retry manifest to disk atomically.

    Uses tmp file + rename pattern. Sets 0o600 mode after rename.
    """
```

### `add_or_update_failures(manifest: RetryManifest, failures: list[FailureEntry], *, now: datetime) -> RetryManifestDelta`

본 통합 명령 호출의 실패 영상을 매니페스트에 추가하거나 (기존에 있으면) 갱신한다. 변화 요약을 RetryManifestDelta 로 반환.

```python
def add_or_update_failures(
    manifest: RetryManifest,
    failures: list[FailureEntry],
    *,
    now: datetime,
) -> RetryManifestDelta:
    """Add new failures and update existing entries.

    For each failure:
    - If entry with same video_id exists, increment attempt_count and
      update last_attempt_at, failed_stage, failure_reason.
    - If entry absent, append new entry with attempt_count=1.

    Returns delta summary (added_count, resolved_count=0, remaining_count).
    """
```

### `resolve_successes(manifest: RetryManifest, succeeded_video_ids: set[str]) -> RetryManifestDelta`

본 호출에서 성공 처리된 영상을 매니페스트에서 제거한다 (resolved).

```python
def resolve_successes(
    manifest: RetryManifest,
    succeeded_video_ids: set[str],
) -> RetryManifestDelta:
    """Remove entries whose video_id is in succeeded set.

    Returns delta summary (added_count=0, resolved_count, remaining_count).
    """
```

### `select_retry_targets(manifest: RetryManifest, *, max_attempts: int = 5) -> list[str]`

다음 통합 명령 호출 시 우선 재시도 대상 video_id 목록을 반환. `attempt_count >= max_attempts` 인 entry 는 운영자 수동 점검 대상으로 분리하기 위해 자동 재시도 큐에서 제외.

```python
def select_retry_targets(
    manifest: RetryManifest,
    *,
    max_attempts: int = 5,
) -> list[str]:
    """Return video_ids eligible for automated retry.

    Excludes entries with attempt_count >= max_attempts (operator
    must intervene manually).
    """
```

## Schema Versioning

본 contract 는 `schema_version = 1` 을 정의한다. 향후 schema 변경 시:

1. 새 버전 (예: `2`) 을 정의하고 contract 갱신
2. `load_manifest()` 가 옛 버전을 읽으면 migration 함수 호출
3. migration 후 `save_manifest()` 로 새 버전으로 저장

본 spec 의 implementation 시점에는 버전 `1` 만 존재하므로 migration 함수는 신설하지 않음 (over-engineering 회피).

## Acceptance Matrix

| 시나리오 | 입력 | 기대 결과 |
|---|---|---|
| 빈 매니페스트 로드 | 파일 부재 | `RetryManifest(entries=[], schema_version=1, alias=<from-context>)` 반환 |
| 단일 실패 추가 | `add_or_update_failures([FailureEntry(video_id="abc", ...)])` | entries 1 개, attempt_count=1, delta.added_count=1 |
| 같은 영상 재실패 | 1 회 실패 후 같은 video_id 재추가 | entries 1 개, attempt_count=2, last_attempt_at 갱신 |
| 성공 해소 | `resolve_successes({"abc"})` | entries 0 개, delta.resolved_count=1 |
| schema_version 불일치 | `schema_version: 99` 파일 로드 | `ValueError` 명시적 raise |
| alias 불일치 | manifest 의 alias 가 context alias 와 다름 | `ValueError` 명시적 raise |
| atomic write 부분 실패 | tmp 파일 작성 도중 crash 시뮬레이션 | 기존 매니페스트 파일 그대로 보존 (corrupt 안 됨) |
| 최대 시도 초과 | attempt_count=5 인 entry + max_attempts=5 | `select_retry_targets` 에서 해당 video_id 제외 |
| 0600 권한 보장 | save_manifest 후 stat 확인 | mode == 0o600 |
