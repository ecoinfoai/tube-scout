# Contract: services/takeout_ingest.py

**Module**: `src/tube_scout/services/takeout_ingest.py` (신규)
**Spec FR mapping**: FR-001~FR-009.
**Boundary**: B-1 (alias resolver), B-2 (v4 migration), B-5 (audit_writer).

---

## 함수 시그니처

```python
from pathlib import Path
from tube_scout.models.content import ChannelMetadata, VideoMetadata

def parse_takeout_csv_metadata(
    takeout_dir: Path,
) -> tuple[ChannelMetadata, list[VideoMetadata]]:
    """Parse Takeout export metadata CSVs.

    Args:
        takeout_dir: Takeout 압축 해제 루트 (예: /path/to/takeout-20260511.../Takeout).

    Returns:
        (channel_meta, video_meta_list) tuple. video_meta는 video_id 기준 dedup.

    Raises:
        FileNotFoundError: 필수 카테고리(`동영상*.csv`, `채널.csv`)가 takeout_dir 하위에 없을 때.
        ValueError: CSV 형식 오류(필수 컬럼 부재).
    """

def assemble_channel_work_dir(
    takeout_dir: Path,
    channel_alias: str,
    work_root: Path,
    use_symlinks: bool = True,
) -> Path:
    """Assemble per-channel unified work dir with mp4 symlinks (or copies).

    Args:
        takeout_dir: Takeout 루트.
        channel_alias: spec 003 alias.
        work_root: data/ 디렉터리 루트.
        use_symlinks: True=symlink (POSIX), False=copy.

    Returns:
        채널 work_dir 경로 (`work_root/<alias>/`).

    Raises:
        OSError: symlink 생성 실패 (Windows 등 비-POSIX OS).
    """

def ingest_takeout(
    takeout_dir: Path,
    channel_alias: str,
    db_path: Path,
    work_root: Path,
    *,
    use_symlinks: bool = True,
    dry_run: bool = False,
) -> IngestResult:
    """End-to-end Takeout ingestion (FR-001/FR-002/FR-009).

    Steps:
      1. Validate alias via spec 003 resolver (B-1). Reject unknown alias.
      2. Parse metadata CSVs (parse_takeout_csv_metadata).
      3. Run evidence-score mapping (services/evidence_score.py).
      4. Apply _manual_mappings.csv overrides (FR-006).
      5. Persist channel_metadata + video_metadata to SQLite (v4 migrate on demand).
      6. Write channel_meta.json + videos_meta.json atomic.
      7. Assemble work_dir with mp4 symlinks (FR-009).
      8. Write _ambiguous_mappings.csv for unresolved cases (FR-005).
      9. Append audit rows to takeout_ingest_audit.csv (B-5).

    Args:
        takeout_dir: Takeout 루트.
        channel_alias: 자교 alias.
        db_path: content_reuse.db 경로 (v3 또는 v4 — v4 미만이면 migrate_to_v4 자동 호출).
        work_root: data/ 루트.
        use_symlinks: see assemble_channel_work_dir.
        dry_run: True 시 DB write 0, 매핑 결과만 stdout.

    Returns:
        IngestResult — count summary + ambiguous count + ignored CSV count.

    Raises:
        ValueError: alias 미등록.
        FileNotFoundError: takeout_dir 경로 오류.
    """
```

---

## 데이터 클래스

```python
class IngestResult(BaseModel):
    channel_id: str
    channel_alias: str
    total_videos: int                # video_metadata에 적재된 row 수
    new_videos: int                  # 이번 호출에서 신규 적재된 row 수
    high_confidence_mappings: int
    medium_confidence_mappings: int
    ambiguous_mappings: int
    unmapped_filenames: int          # mp4 파일은 있으나 video_id 매핑 불가
    ignored_csv_count: int           # FR-008 무시 정책 적용 CSV 카테고리 수
    dry_run: bool
```

---

## CSV 무시 정책 (FR-008)

다음 패턴의 파일·디렉터리는 `ingest_takeout` 진입 시 명시적으로 검출 후 audit-log "ignored_by_policy" + skip:

| 패턴 | 사유 |
|---|---|
| `동영상 녹화*.csv` | 위경도 데이터, scope OUT |
| `동영상 텍스트*.csv` | 제목/설명 세그먼트, scope OUT |
| `댓글.csv` | 자교 댓글 무시 정책 (`memory/project_no_comments`) |
| `재생목록*.csv` | scope OUT |
| `구독정보*.csv` | scope OUT |
| `시청 기록/*.html` | 개인정보, scope OUT |
| `검색 기록.html` | 동상 |

audit row 형식 (E-12): `video_id="n/a", result="skip", reason="ignored_by_policy", mp4_filename="<csv_filename>", match_confidence="n/a", score=0, timestamp=<ISO>`.

---

## Idempotency Guarantee (FR-007)

- 모든 SQLite INSERT는 `INSERT OR IGNORE` — 같은 video_id 재ingestion은 첫 row 권위 유지.
- channel_metadata UPDATE는 `takeout_root_hint` 와 `ingested_at` 만 — 나머지 컬럼 변경 0.
- JSON write는 atomic tempfile + rename.
- Symlink 재생성은 `os.path.exists` 체크 후 skip (`--force` 옵션은 본 함수에 없음 — CLI 레벨에서만).

---

## 테스트 진입점 (TDD RED-first)

- `tests/contract/test_takeout_ingest_contract.py`:
  - `test_parse_takeout_csv_metadata_returns_dedup_video_list` (1 video 중복 row → 1개만)
  - `test_assemble_channel_work_dir_creates_symlinks` (POSIX, tmp_path)
  - `test_ingest_takeout_rejects_unknown_alias` (raises ValueError)
  - `test_ingest_takeout_idempotent_two_runs` (DB row count 동일)
  - `test_ingest_takeout_dry_run_no_db_write` (DB 변경 0)
  - `test_ignored_categories_audit_logged` (8 카테고리 모두 audit row)
- `tests/unit/test_takeout_ingest_csv_parser.py`:
  - 분할 CSV(`동영상.csv`, `동영상(1).csv`, …) 통합 + dedup.
  - 밀리초 → 초 변환 검증.
  - `채널.csv`에서 channel_id 추출.

---

## 출력 파일 schema

`<channel_work_dir>/channel_meta.json` (E-1 JSON 표현).
`<channel_work_dir>/videos_meta.json` (E-2 JSON 표현의 list).
`<channel_work_dir>/01_collect/_ambiguous_mappings.csv` (E-3 schema).
`<channel_work_dir>/01_collect/takeout_ingest_audit.csv` (E-12 takeout_ingest fieldnames).
