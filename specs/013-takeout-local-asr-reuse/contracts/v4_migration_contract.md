# Contract: storage/content_db.py — migrate_to_v4

**Module**: `src/tube_scout/storage/content_db.py` (기존, 본 spec에서 확장)
**Spec FR mapping**: FR-043~FR-045.
**Boundary**: B-2 (spec 007 v2 → v4 누적), B-6 (spec 012 v3 보존).

---

## 함수 시그니처

```python
from pathlib import Path

def migrate_to_v4(db_path: Path) -> None:
    """Migrate content_reuse.db from v3 → v4. Idempotent.

    Adds two new tables (channel_metadata, video_metadata) and alters
    three existing tables (processing_status, quality_results, comparison_results)
    to add the columns required by spec 013.

    Pre-conditions:
        - db_path exists and is a v3-or-higher SQLite database
          (PRAGMA user_version >= 3).

    Post-conditions:
        - PRAGMA user_version == 4.
        - channel_metadata and video_metadata tables exist with the schema in data-model.md §E-1/E-2.
        - processing_status has columns match_confidence (TEXT) and caption_source_detail (TEXT).
        - quality_results has column asr_quality_flags (TEXT).
        - comparison_results has columns audio_fp_hamming (INTEGER),
          audio_fp_best_offset (REAL), audio_fp_overlap_seconds (REAL),
          source_type_pair (TEXT).
        - All existing rows preserved (no data loss).

    Args:
        db_path: Path to content_reuse.db (assumed v3 schema present).

    Raises:
        ValueError: PRAGMA user_version < 3 (run migrate_to_v3 first).
        FileNotFoundError: db_path does not exist.
    """

def _add_column_if_missing(
    cur: sqlite3.Cursor,
    table: str,
    column: str,
    type_: str,
) -> bool:
    """Add a column to a table only if it does not already exist.

    Args:
        cur: SQLite cursor.
        table: Table name.
        column: Column name to add.
        type_: SQLite type (e.g., 'TEXT', 'INTEGER', 'REAL').

    Returns:
        True if column was added (i.e., it was missing), False if it
        already existed (no-op).
    """
```

---

## v4 schema SQL (executescript)

```sql
-- 신규 테이블 2개
CREATE TABLE IF NOT EXISTS channel_metadata (
    channel_id           TEXT PRIMARY KEY,
    channel_alias        TEXT NOT NULL,
    title                TEXT,
    country              TEXT,
    privacy_status       TEXT,
    source               TEXT NOT NULL,
    takeout_root_hint    TEXT,
    ingested_at          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS video_metadata (
    video_id             TEXT PRIMARY KEY,
    channel_id           TEXT NOT NULL,
    title                TEXT NOT NULL,
    duration_seconds     REAL,
    language             TEXT,
    category             TEXT,
    privacy_status       TEXT,
    created_at           TEXT,
    published_at         TEXT,
    source               TEXT NOT NULL,
    match_confidence     TEXT,
    mp4_relative_path    TEXT,
    ingested_at          TEXT NOT NULL,
    FOREIGN KEY (channel_id) REFERENCES channel_metadata(channel_id)
);

CREATE INDEX IF NOT EXISTS idx_video_meta_channel ON video_metadata(channel_id);
CREATE INDEX IF NOT EXISTS idx_video_meta_privacy ON video_metadata(privacy_status);
```

ALTER 컬럼은 `_add_column_if_missing` 함수로 멱등 적용:

```python
_add_column_if_missing(cur, "processing_status",  "match_confidence",       "TEXT")
_add_column_if_missing(cur, "processing_status",  "caption_source_detail",  "TEXT")
_add_column_if_missing(cur, "quality_results",    "asr_quality_flags",      "TEXT")
_add_column_if_missing(cur, "comparison_results", "audio_fp_hamming",       "INTEGER")
_add_column_if_missing(cur, "comparison_results", "audio_fp_best_offset",   "REAL")
_add_column_if_missing(cur, "comparison_results", "audio_fp_overlap_seconds","REAL")
_add_column_if_missing(cur, "comparison_results", "source_type_pair",       "TEXT")
```

마지막 `PRAGMA user_version = 4;` 로 마무리.

---

## 자동 진입 정책 (FR-045)

`ingest_takeout`, `transcribe_audio`, `run_nc2_analysis` 등 v4 컬럼 의존 함수들의 진입점에서 `_ensure_v4(db_path)` helper 호출:

```python
def _ensure_v4(db_path: Path) -> None:
    """Ensure the database is at v4. Auto-migrates from v3 if needed."""
    with sqlite3.connect(db_path) as conn:
        cur = conn.cursor()
        cur.execute("PRAGMA user_version;")
        version = cur.fetchone()[0]
    if version < 3:
        raise ValueError(
            f"Database at {db_path} is at version {version}, expected >= 3. "
            "Run migrate_to_v3 first (spec 012 master)."
        )
    if version < 4:
        migrate_to_v4(db_path)
```

운영자가 별도 migration 명령 실행 불필요 — 첫 v4-dependent 작업 시 자동.

---

## 멱등성 검증

같은 DB에 `migrate_to_v4` 를 두 번 호출:
1. 첫 호출: 신규 테이블 생성 + 7개 컬럼 ADD + user_version=4 set.
2. 두 번째 호출: `version >= 4` 검사로 즉시 return.

빈 v4 DB에 직접 호출:
1. `version=0` → ValueError ("Expected user_version >= 3, got 0").

v3에서 직접 호출 (v2 → v3 → v4 누적 검증):
1. spec 012 master가 `migrate_to_v3` 후 user_version=3.
2. 본 spec `migrate_to_v4` 가 user_version=3 → 4.

---

## 테스트 진입점

- `tests/contract/test_v4_migration_contract.py`:
  - `test_migrate_to_v4_signature_matches_contract`
  - `test_migrate_raises_when_version_below_3`
- `tests/unit/test_add_column_if_missing.py`:
  - `test_adds_column_when_missing`
  - `test_no_op_when_column_exists`
  - `test_returns_correct_boolean`
- `tests/integration/test_v4_migration.py`:
  - `test_migrate_v3_to_v4_creates_two_new_tables`
  - `test_migrate_v3_to_v4_adds_7_columns`
  - `test_migrate_v3_to_v4_preserves_existing_rows` (spec 012 9개 audio_fingerprint row, spec 007 sample comparison_results rows 보존)
  - `test_migrate_idempotent_two_calls` (두 번 호출 후 schema 동일)
  - `test_pragma_user_version_set_to_4`
- `tests/integration/test_v3_to_v4_idempotent.py`:
  - spec 012 v3 fixture DB → migrate_to_v4 → 다시 migrate_to_v4 → no-op.
- `tests/integration/test_v4_auto_ensure.py`:
  - `_ensure_v4` 가 v3 DB 자동 migrate.
  - `_ensure_v4` 가 v4 DB no-op.
  - `_ensure_v4` 가 v2 DB에서 ValueError.

---

## Constitution V 준수 (외부 DB 0건)

본 contract는 SQLite ALTER + 신규 테이블 — 외부 DB 도입 없음. spec 007/011/012의 단일 `content_reuse.db` 파일 위치 유지.
