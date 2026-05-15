# CLI Contract: `tube-scout collect takeout`

**Spec**: [../spec.md](../spec.md) | **FR**: FR-001~011, FR-022~023 | **User Story**: US 1, US 3

## Command shape

```
tube-scout collect takeout
    --takeout-dir <path>            # required
    --channel <alias>               # required (channels.json 또는 departments.json 등록 alias)
    [--dry-run]                     # 적재 미수행, IngestResult 만 출력
    [--no-symlinks]                 # 기본은 symlink, 명시 시 copy
    [--db-path <path>]              # 기본 = ~/.local/share/tube-scout/content_reuse.db
    [--work-root <path>]            # 기본 = ./data
    [--json]                        # 결과를 JSON 으로 stdout 출력 (기본은 Rich table)
```

## Inputs

| 옵션 | 타입 | 필수 | 기본값 | 의미 |
|---|---|---|---|---|
| `--takeout-dir` | path | ✅ | — | Google Takeout archive 가 풀린 디렉토리 root (`Takeout/YouTube 및 YouTube Music/` 의 부모) |
| `--channel` | string | ✅ | — | 학과 alias. channels.json 또는 departments.json 중 한 곳 이상에 등록되어 있어야 함 |
| `--dry-run` | flag | ❌ | False | DB 미수정, IngestResult 만 출력 |
| `--no-symlinks` | flag | ❌ | False | mp4 를 copy (POSIX 외 환경 호환) |
| `--db-path` | path | ❌ | `~/.local/share/tube-scout/content_reuse.db` | SQLite v4 파일 |
| `--work-root` | path | ❌ | `./data` | per-alias work directory parent |
| `--json` | flag | ❌ | False | stdout 출력을 JSON 으로 |

## Outputs (stdout)

기본 Rich table (한국어), `--json` 명시 시 JSON.

**JSON shape**:

```json
{
  "channel_id": "UCnh3tm9uQkyA260cAHfl9rg",
  "channel_alias": "nursing",
  "total_videos": 2554,
  "new_videos": 2554,
  "high_confidence_mappings": 9,
  "medium_confidence_mappings": 0,
  "ambiguous_mappings": 0,
  "unmapped_filenames": 0,
  "ignored_csv_count": 26,
  "mp4_present_count": 9,
  "mp4_absent_count": 2545,
  "elapsed_seconds": 14.27,
  "dry_run": false
}
```

## Exit codes

| Code | 의미 | 트리거 |
|---|---|---|
| 0 | 성공 | 적재 완료 또는 dry-run 출력 |
| 1 | 검증 실패 | alias 미등록, takeout_dir 부재, `채널.csv` 없음, 동영상*.csv 0 개 |
| 2 | (예약) | 미사용 |
| 130 | SIGINT | Ctrl+C |

## Audit CSV rows

본 명령은 `data/{alias}/audit.csv` 에 다음 row 들을 append-only 로 추가:

| 시나리오 | result | reason | 추가 컬럼 |
|---|---|---|---|
| mp4 매칭 성공 (high/medium) | success | n/a | match_confidence, score, mp4_filename, elapsed_ms |
| mp4 매칭 ambiguous | skip | multiple_candidates | match_confidence=ambiguous, mp4_filename, elapsed_ms |
| mp4 매칭 unmapped | skip | no_match | match_confidence=unmapped, mp4_filename, elapsed_ms |
| mp4 부재 영상 | skip | no_mp4_in_archive | video_id (mp4_filename=n/a), elapsed_ms |
| 무시된 csv | skip | ignored_by_policy | mp4_filename=`<csv name>`, video_id=n/a |
| privacy 알 수 없는 한글 값 | skip | unknown_privacy_value | raw_value=`<원본 한글>`, video_id, elapsed_ms |

## Error cases

| 입력 상태 | 출력 | exit |
|---|---|---|
| `--channel nursing` 미등록 | stderr: "Channel alias 'nursing' is not registered. Available: [...]" | 1 |
| `--takeout-dir` 경로 부재 | stderr: "takeout_dir not found: <path>" | 1 |
| `채널.csv` 부재 | stderr: "채널.csv not found under <channel_dir>" | 1 |
| `동영상.csv` / `동영상(N).csv` 모두 부재 | stderr: "No 동영상.csv or 동영상(N).csv files found under <meta_dir>" | 1 |
| `채널 제목(원본)` 컬럼 부재 (미래 Takeout 포맷 변경) | stderr: "Missing required column in 채널.csv: '채널 제목(원본)'" | 1 |
| `동영상 ID`/`동영상 제목(원본)`/`근사치 길이(밀리초)`/`채널 ID`/`개인 정보 보호`/`동영상 생성 타임스탬프` 중 하나라도 부재 | stderr: "Missing required columns in <file>: {col}" | 1 |
| alias 가 channels.json 과 departments.json 양쪽에 있지만 channel_id 불일치 (B-1+B-2) | stderr: "alias <X> mismatch between channels.json and departments.json — analysis commands blocked. Run 'tube-scout admin list --json' to inspect." | 1 |

## Cross-Spec Boundary 검증 (B-3, B-4, B-5)

- B-3: `ingest_takeout()` 함수 시그니처 보존 (`takeout_dir, channel_alias, db_path, work_root, *, use_symlinks, dry_run → IngestResult`).
- B-4: SQLite v4 스키마 보존 + `_ensure_v4()` 의 멱등 마이그레이션 흐름.
- B-5: audit_writer 의 컬럼 셋 보존 + reason 어휘 확장 + elapsed_ms 신규.

## Idempotence guarantees

- 같은 archive 두 번 적재: `new_videos=0`, `mp4_added=0`, DB 행 변경 없음. audit row 는 append-only 로 누적.
- 다른 archive part 의 같은 video_id: first-write-wins (R-8). DB 메타 변경 없음, 새 mp4 본체가 있으면 `mp4_relative_path` 만 UPDATE.
