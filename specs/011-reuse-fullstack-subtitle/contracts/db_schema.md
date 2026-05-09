# DB Schema Contract: spec 011 SQLite migration

**Feature**: 011-reuse-fullstack-subtitle
**Target file**: `projects/{job-id}/02_analyze/content/content_reuse.db` (spec 007 인계)
**Migration entry point**: `tube_scout.storage.content_db.migrate_to_v2(db_path: Path) -> None`

본 contract는 `tests/contract/test_db_schema_v2_contract.py` 의 ground truth다. Migration은 idempotent해야 한다 (중복 호출 시 에러 없이 no-op).

---

## 1. Migration order

`migrate_to_v2` 는 다음 순서로 실행:

1. **Read existing schema state** — `PRAGMA table_info(comparison_results)` 와 `SELECT name FROM sqlite_master WHERE type='table'`로 현재 컬럼·테이블 목록 추출.
2. **ALTER `comparison_results`** — data-model.md §2 의 신규 컬럼 10개를 누락된 것만 ADD. 모두 NULLable이거나 기본값 보유.
3. **CREATE 신규 테이블** — `professor_pool`, `professor_pool_membership`, `baseline_corpus`, `phrase_whitelist`, `pair_checkpoint`, `match_spans` 6개. 모두 `IF NOT EXISTS`.
4. **CREATE 인덱스** — `idx_cr_mode`, `idx_cr_prof`, `idx_cr_pattern`, `idx_span_cmp`. 모두 `IF NOT EXISTS`.
5. **Backfill** — 기존 `comparison_results` row의 `matching_mode` 가 NULL 또는 missing 이면 `'M-default'`로 UPDATE (DEFAULT 가 적용되지 않은 row 대비).
6. **Verify** — migration 후 `PRAGMA integrity_check` 가 `ok` 반환 + 모든 신규 컬럼·테이블이 존재하는지 단언. 실패 시 RuntimeError.

---

## 2. Backward-compat 보장

| 보장 | 검증 방법 |
|---|---|
| spec 007 row의 spec 007 컬럼 값은 변경 없음 | migration 전후 SHA-256 of `(id, source_video_id, target_video_id, i1_hash_match, i2_cosine_similarity, i3_change_rate, i4_new_term_count, i5_duration_diff_seconds, suspicion_score, grade, review_status)` 동일 |
| spec 007 row 의 신규 컬럼은 NULL (matching_mode 제외) | `SELECT count(*) FROM comparison_results WHERE i6_longest_contiguous_seconds IS NOT NULL AND id IN (<spec007 row ids>)` = 0 |
| spec 007 코드 경로가 변경 없이 작동 | spec 007 통합 테스트 모두 통과 (no regression) |
| 기존 `quality_results`, `processing_status`, `fingerprint_hashes` 테이블 변경 없음 | 스키마 비교 |

---

## 3. New table DDL (정본)

data-model.md §12 와 동일. 본 문서는 contract 테스트가 비교할 정본이다. 차이가 발견되면 contract 테스트 실패 → schema 정의 단일 출처 유지.

---

## 4. CHECK constraints

| 테이블·컬럼 | 제약 |
|---|---|
| `comparison_results.matching_mode` | `CHECK (matching_mode IN ('M-default', 'M-nC2'))` |
| `comparison_results.review_status` | `CHECK (review_status IN ('UNREVIEWED', 'PENDING', 'CONFIRMED_DUPLICATE', 'FALSE_POSITIVE'))` |
| `comparison_results.reuse_pattern` | `CHECK (reuse_pattern IS NULL OR reuse_pattern IN ('whole-same-week','scattered-same-week','whole-different-week','scattered-different-week'))` |
| `match_spans.length_seconds` | `CHECK (length_seconds >= 0)` |
| `pair_checkpoint.status` | `CHECK (status IN ('in_progress','completed','aborted'))` |

ALTER TABLE은 SQLite에서 CHECK constraint 추가가 제한적이므로 신규 컬럼은 가능하면 CREATE TABLE 시 정의, ALTER 추가 시는 service-layer Pydantic + service-layer ValueError 가 1차 방어선.

---

## 5. Index strategy

| Index | 의도 |
|---|---|
| `idx_cr_mode (matching_mode)` | 보고서·CLI에서 mode별 필터 |
| `idx_cr_prof (professor_id)` | nC2 결과 조회 |
| `idx_cr_pattern (reuse_pattern)` | 4 패턴 분리 보고 |
| `idx_span_cmp (comparison_id)` | 시간축 시각화 시 한 쌍의 모든 span 조회 |

기존 spec 007의 `idx_cr_grade`, `idx_cr_review`, `idx_fp_hash` 는 그대로 유지.

---

## 6. Migration 실패 시 동작

- `PRAGMA integrity_check` 가 `ok` 가 아니면 RuntimeError + 영문 메시지.
- ALTER가 실패하면 (예: 동시 액세스로 인한 lock) — `OperationalError` 를 잡아 사용자에게 actionable 메시지로 표시 후 exit code 2.
- migration 부분 적용을 막기 위해 모든 ALTER + CREATE 는 단일 트랜잭션 안에서 수행 (`BEGIN ... COMMIT`).
- migration 시도가 실패하면 DB 파일은 ALTER 전 상태로 자동 롤백 (SQLite WAL 동작).

---

## 7. Schema version stamping

`policy_config` 또는 별도 `_schema_version` 테이블에 `schema_version = 'spec-011-v1'` 단일 row. 이후 spec(예: spec 012)이 이 값을 보고 재migration 여부 결정.

```sql
CREATE TABLE IF NOT EXISTS _schema_version (
    spec TEXT PRIMARY KEY,
    version TEXT NOT NULL,
    applied_at TEXT NOT NULL
);
INSERT OR REPLACE INTO _schema_version (spec, version, applied_at) VALUES ('spec-011', 'v1', '<ISO8601>');
```

---

## 8. Contract test의 책임

`tests/contract/test_db_schema_v2_contract.py` 가 다음을 검증:

1. spec 007 fixture DB로 시작 → `migrate_to_v2` 1회 호출 → 모든 신규 컬럼·테이블·인덱스 존재.
2. 같은 DB에 `migrate_to_v2` 한 번 더 호출 → 에러 없이 종료, schema 변경 없음 (idempotent).
3. spec 007 row의 spec 007 컬럼 값이 변경되지 않음 (해시 비교).
4. spec 007 row의 `matching_mode = 'M-default'` 로 backfill 됨.
5. CHECK constraint가 잘못된 enum 값 INSERT를 거부.
6. `_schema_version` 테이블에 `spec-011 / v1` 항목 존재.
