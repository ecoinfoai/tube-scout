# Phase 1 Data Model: Takeout 기반 로컬 ASR + 강의 영상 재사용 판정 + 자막 KB Export

**Spec**: [spec.md](./spec.md) · **Plan**: [plan.md](./plan.md) · **Research**: [research.md](./research.md)

본 문서는 v4 마이그레이션 schema, 신규 entity 9종, 그리고 spec 007/010/011/012와 공유하는 boundary diff를 동결한다. 모든 schema는 멱등 적용 가능하며 기존 row 무결성을 보존한다.

---

## E-1. ChannelMetadata (v4 신규 테이블)

자교 채널 메타. Takeout `채널.csv`에서 추출, SQLite + JSON 이중 적재(분석 파이프 호환).

**SQLite v4 DDL**:

```sql
CREATE TABLE IF NOT EXISTS channel_metadata (
    channel_id           TEXT PRIMARY KEY,           -- YouTube channel ID (UCxxxx...)
    channel_alias        TEXT NOT NULL,              -- spec 003 alias resolver의 키 (예: 'nursing')
    title                TEXT,                       -- 채널 표시명
    country              TEXT,                       -- ISO 3166-1 alpha-2
    privacy_status       TEXT,                       -- 'public' | 'unlisted' | 'private'
    source               TEXT NOT NULL,              -- 'takeout' | 'api' | 'manual'
    takeout_root_hint    TEXT,                       -- 최근 ingestion 시 절대 경로 (운영자 메모용, 런타임 결합 미사용)
    ingested_at          TEXT NOT NULL               -- ISO 8601 timezone-aware
);
```

**Pydantic 모델** (`models/content.py` 신규):

```python
class ChannelMetadata(BaseModel):
    channel_id: str = Field(..., min_length=1)
    channel_alias: str = Field(..., min_length=1)
    title: str | None = None
    country: str | None = Field(None, max_length=2)
    privacy_status: Literal["public", "unlisted", "private"] | None = None
    source: Literal["takeout", "api", "manual"]
    takeout_root_hint: str | None = None
    ingested_at: datetime
```

**JSON 표현** (`<channel_work_dir>/channel_meta.json`):

```json
{
  "channel_id": "UCxxxxxxxxxxxxxxxxxxxxxx",
  "channel_alias": "nursing",
  "title": "간호학과 채널",
  "country": "KR",
  "privacy_status": "unlisted",
  "source": "takeout",
  "takeout_root_hint": "/home/kjeong/data/takeout-20260511T130817Z-3-001",
  "ingested_at": "2026-05-13T10:30:00+09:00"
}
```

**Lifecycle**:
- 생성: `collect takeout` 최초 ingestion 시.
- 갱신: 같은 채널 재ingestion 시 `takeout_root_hint`와 `ingested_at` 만 갱신(나머지 변경 0). 멱등.
- 삭제: 운영자 수동 only (CLI 미제공).

**Boundary**: B-1 (spec 003 alias resolver) — `channel_alias` 컬럼이 alias resolver의 키와 1:1.

---

## E-2. VideoMetadata (v4 신규 테이블)

영상 메타. Takeout `동영상*.csv` 13개에서 추출, video_id 기준 deduplicate.

**SQLite v4 DDL**:

```sql
CREATE TABLE IF NOT EXISTS video_metadata (
    video_id             TEXT PRIMARY KEY,
    channel_id           TEXT NOT NULL,
    title                TEXT NOT NULL,
    duration_seconds     REAL,
    language             TEXT,
    category             TEXT,
    privacy_status       TEXT,                       -- 'public' | 'unlisted' | 'private'
    created_at           TEXT,                       -- 영상 생성 ISO 8601
    published_at         TEXT,                       -- 영상 공개 ISO 8601 (private 영상은 NULL)
    source               TEXT NOT NULL,              -- 'takeout' | 'api'
    match_confidence     TEXT,                       -- 'high' | 'medium' | 'ambiguous'
    mp4_relative_path    TEXT,                       -- 채널 work_dir 기준 상대 경로 (예: 'videos/5-1.임경민.mp4')
    ingested_at          TEXT NOT NULL,
    FOREIGN KEY (channel_id) REFERENCES channel_metadata(channel_id)
);
CREATE INDEX IF NOT EXISTS idx_video_meta_channel ON video_metadata(channel_id);
CREATE INDEX IF NOT EXISTS idx_video_meta_privacy ON video_metadata(privacy_status);
```

**Pydantic 모델**:

```python
class VideoMetadata(BaseModel):
    video_id: str = Field(..., min_length=1, max_length=20)
    channel_id: str = Field(..., min_length=1)
    title: str = Field(..., min_length=1)
    duration_seconds: float | None = Field(None, ge=0.0)
    language: str | None = None
    category: str | None = None
    privacy_status: Literal["public", "unlisted", "private"] | None = None
    created_at: datetime | None = None
    published_at: datetime | None = None
    source: Literal["takeout", "api"]
    match_confidence: Literal["high", "medium", "ambiguous"] | None = None
    mp4_relative_path: str | None = None
    ingested_at: datetime
```

**JSON 표현** (`<channel_work_dir>/videos_meta.json`): 위 schema 그대로의 list. 분석 파이프 호환을 위해 SQLite와 이중 적재(source-of-truth는 SQLite).

**Lifecycle**:
- 생성: `collect takeout` 시 메타 CSV row → SQLite + JSON 동시 적재. `INSERT OR IGNORE` — 같은 video_id 재ingestion은 첫 row 권위 유지(idea Edge Case "처음 들어온 메타를 권위로").
- 갱신: 운영자가 `_manual_mappings.csv` 또는 `_ambiguous_mappings.csv`를 편집하고 재ingestion 시 `match_confidence` / `mp4_relative_path` UPDATE.
- 삭제: 운영자 수동 only.

**Boundary**: B-2 (spec 007 v2 schema preserve), B-4 (spec 011 분석이 `professor_pool_membership` JOIN으로 video_metadata 참조 가능).

---

## E-3. TakeoutMapping (논리 entity — CSV 파일)

mp4 ↔ video_id 매핑 결정 — Evidence Score + 운영자 결정. SQLite 영속 결과는 `video_metadata.match_confidence` + `.mp4_relative_path`로 surface.

**파일 1: `_ambiguous_mappings.csv` (운영자 검토 큐)**

| 컬럼 | 형식 | 비고 |
|---|---|---|
| `mp4_filename` | TEXT | Takeout 디렉터리 상대 경로 |
| `candidate_video_ids` | TEXT | 쉼표 구분, score 내림차순 |
| `scores` | TEXT | 쉼표 구분, 위와 동일 순서 |
| `signals_breakdown` | TEXT (JSON) | 각 신호별 점수 — `{"exact_title": 0, "normalized_title": 30, "duration_match": 25, "size_ratio": 5, "mtime_match": 0}` |
| `reason` | TEXT | `'low_score'` / `'tie'` / `'no_candidates'` |
| `resolved_video_id` | TEXT (운영자 입력) | 비어 있으면 미해결, 입력 시 다음 ingestion이 권위 반영 |
| `resolved_at` | TEXT (운영자 입력) | ISO 8601 |

**파일 2: `_manual_mappings.csv` (운영자 1급 override)**

| 컬럼 | 형식 | 비고 |
|---|---|---|
| `mp4_filename` | TEXT | Takeout 상대 경로 |
| `video_id` | TEXT | 운영자 결정 |
| `note` | TEXT | 운영자 메모 (선택) |

**Lifecycle**:
- 생성: ingestion 시 ambiguous 케이스가 발견되면 `_ambiguous_mappings.csv`에 row 추가(또는 갱신). `_manual_mappings.csv`는 운영자가 사전 작성.
- 해결: 운영자가 `_ambiguous_mappings.csv`의 `resolved_video_id` 입력 후 ingestion 재실행 → 해결된 row가 SQLite UPDATE 발생, 다음 ingestion에서 자동 매핑 단계 우회.
- 멱등: 같은 ambiguous 입력은 같은 row 갱신만 발생 — 중복 row 없음.

**Boundary**: 본 spec 신규, 외부 spec과 boundary 없음.

---

## E-4. AudioArtifact (논리 entity — 파일시스템)

mp4에서 추출된 16 kHz mono PCM WAV. 통합 모드(`collect process-audio`)는 영상별 즉시 삭제, 분리 모드(`collect audio-extract`)는 캐시 누적.

**Path**: `<audio_cache_dir>/<video_id>.wav` (기본 `/tmp/tube-scout-audio/`, `--audio-cache-dir`로 override)

**규격**:

| Attribute | Value | Source |
|---|---|---|
| `format` | WAV (16-bit PCM) | ffmpeg `-c:a pcm_s16le` |
| `sample_rate` | 16000 Hz | ffmpeg `-ar 16000` |
| `channels` | 1 (mono) | ffmpeg `-ac 1` |
| `duration` | 영상 원본 동일 (±0.1초) | ffprobe 일치 검증 |

**Lifecycle invariants (C-1)**:
- 통합 모드(`collect process-audio`): per-video [추출 → 지문 → STT → 정규화 → WAV 삭제] 한 트랜잭션. 영상 1개의 어떤 단계가 실패해도 WAV는 try/finally 절로 삭제 보장. `--keep-audio` 시만 보존.
- 분리 모드(`collect audio-extract`): 캐시에 누적. 다음 명령(`collect fingerprint --source local --input-kind wav_16k`, `collect transcripts --source asr`)이 그대로 입력으로 사용. 운영자 수동 cleanup.
- 비정상 종료(SIGINT/SIGTERM): 통합 모드의 try/finally가 실행되도록 SignalHandler 등록(spec 012 패턴 `build_signal_handler`). audit-log "interrupted_audio_cleanup".
- 멱등: 동일 video_id의 wav가 캐시에 존재하면 재추출 0(`--force`로 override).

**Persistence policy (Constitution V + C-1)**: 영구 보존 미허용. `--keep-audio` 는 디버깅 옵션 — 운영자 의도된 보존.

**Boundary**: B-12 (flake.nix `ffmpeg` system dep).

---

## E-5. AudioFingerprint (spec 012 그대로 — 본 spec 변경 0)

chromaprint 음원 지문. SQLite v3 `audio_fingerprint` 테이블 — spec 012 master 권위.

```sql
CREATE TABLE IF NOT EXISTS audio_fingerprint (
    video_id     TEXT PRIMARY KEY,
    fingerprint  BLOB NOT NULL,
    duration     REAL NOT NULL,
    extracted_at TEXT NOT NULL,
    source       TEXT NOT NULL DEFAULT 'fpcalc:1.6.0'
);
```

**본 spec 변경 0**: 컬럼 추가·삭제 없음. `services/audio_fingerprint.py::extract_chromaprint_fingerprint`, `storage/content_db.py::insert_audio_fingerprint` 그대로 호출. `fingerprint_input_policy` 분기는 호출 측(`cli/collect.py`)에서 `--input-kind` 옵션 처리.

**Boundary**: B-6, B-7.

---

## E-6. Transcript (Raw, spec 010 schema)

자막 raw — ASR 또는 API caption 출처. spec 010 schema 그대로.

**JSON schema** (`01_collect/transcripts/<video_id>.json`):

```json
{
  "video_id": "sUJbkkYzNGc",
  "language": "ko",
  "source": "whisper",
  "caption_source_detail": "asr:faster-whisper:large-v3:int8_float16",
  "fetched_at": "2026-05-13T11:00:00+09:00",
  "segments": [
    {"start": 0.0, "end": 3.5, "text": "안녕하세요 정광석 교수입니다"},
    {"start": 3.5, "end": 8.2, "text": "오늘은 간호연구방법론 8주차 1차시입니다"}
  ]
}
```

**Field constraints**:
- `video_id`: YouTube video ID (11자, alnum + `_-`).
- `language`: BCP-47 (현재 `ko`).
- `source`: enum — `whisper` | `transcript_api` | `captions_api` (spec 010 호환, 본 spec은 `whisper` 만 신규 산출).
- `caption_source_detail`: 본 spec 신규 — 모델·정밀도 식별자. 형식 `'asr:faster-whisper:<size>:<compute_type>'` 또는 `'api:captions_api'`.
- `segments[].start`, `.end`: float seconds.
- `segments[].text`: 정규화 전 원본 텍스트.

**Lifecycle (C-1)**:
- 생성: `collect transcripts --source asr` 또는 `--source captions_api` 시 atomic write.
- 갱신: `--force` 시만, 같은 atomic write.
- 삭제: 운영자 수동 only. 자동 retention 없음.

**Single-source rule (FR-024)**: 같은 video_id에 ASR과 API caption이 동시 존재 금지. 충돌 발견 시 actionable 영문 메시지 후 종료(자동 우선순위 없음).

**Boundary**: B-3.

---

## E-7. TranscriptNormalized (신규 — Text Normalizer 출력)

정규화 자막. 분석 파이프라인 입력의 단일 표준 형식.

**JSON schema** (`01_collect/transcripts_normalized/<video_id>.json`):

```json
{
  "video_id": "sUJbkkYzNGc",
  "language": "ko",
  "source_type": "asr",
  "normalizer_version": "v1.0",
  "normalized_at": "2026-05-13T11:05:00+09:00",
  "segments": [
    {"start": 0.0, "end": 3.5, "text": "안녕하세요 정광석 교수입니다"},
    {"start": 3.5, "end": 8.2, "text": "오늘은 간호연구방법론 8주차 1차시입니다"}
  ]
}
```

**Field constraints**:
- `source_type`: `'asr'` | `'api'` | `'manual'` — Raw 출처 분기(`comparison_results.source_type_pair` 결합용).
- `normalizer_version`: research §R-10 — `v1.0` 동결, 향후 규칙 변경 시 bump.
- `segments[].text`: 정규화 결과(구두점 제거, NFC, lowercase Latin, ASR meta-marker strip, whitespace collapse).

**Lifecycle**:
- 생성: `collect transcripts --auto-normalize`(기본 on) 또는 `process normalize-transcripts` 시 atomic write.
- 갱신: `--force` 또는 normalizer_version 변경 시.
- 삭제: 운영자 수동 only.
- 멱등: 같은 raw + 같은 normalizer_version 입력은 같은 결과.

**Boundary**: 본 spec 신규. 분석(B-4)이 단일 입력으로 사용.

---

## E-8. ProcessingStatus v4 (확장)

기존 spec 007 테이블 + v4 신규 컬럼 + enum 확장.

**SQLite v4 ALTER**:

```sql
-- 컬럼 추가 (NULL 허용, 기존 row 무결성)
ALTER TABLE processing_status ADD COLUMN match_confidence TEXT;
ALTER TABLE processing_status ADD COLUMN caption_source_detail TEXT;
-- CHECK constraint 도입은 follow-up migration (R-11)
```

**Python enum 확장** (`models/content.py`):

```python
VALID_PROCESSING_STATUSES = frozenset({
    "pending", "collecting", "collected",
    "fingerprinted", "compared", "failed", "no_caption",
    "asr_in_progress", "asr_failed",          # v4 신규
})

VALID_CAPTION_SOURCES = frozenset({"transcript_api", "captions_api", "whisper"})  # 변경 0

VALID_MATCH_CONFIDENCES = frozenset({"high", "medium", "ambiguous"})  # v4 신규
```

**State diagram**:

```
        ┌──────────┐
        │ pending  │ (기본)
        └────┬─────┘
             │ collect takeout
             ▼
        ┌──────────┐
        │ collected│  caption_source=NULL, match_confidence ∈ {high, medium, ambiguous}
        └────┬─────┘
             │ collect transcripts (asr) / captions_api
             ▼
        ┌─────────────────┐
        │asr_in_progress  │  (워커 atomic claim)
        └────┬──────┬─────┘
             │      │ 실패
             │성공   ▼
             │  ┌──────────┐
             │  │asr_failed│  (운영자 --retry-failed 시 직접 다시 asr_in_progress로 — C-5)
             │  └──────────┘
             ▼
        ┌──────────┐
        │collected │  caption_source='whisper' or 'captions_api', caption_source_detail 갱신
        └────┬─────┘
             │ fingerprint extract
             ▼
        ┌──────────────┐
        │fingerprinted │
        └────┬─────────┘
             │ M-nC2 compare
             ▼
        ┌──────────┐
        │ compared │
        └──────────┘
```

`failed`와 `no_caption`은 기존 spec 007 의미 그대로(공개 영상 자막 부재 등). `asr_failed`는 본 spec 신규 — ASR 단계 한정 실패.

**Atomic claim transaction (C-5, R-8)**:

```sql
BEGIN IMMEDIATE;
UPDATE processing_status
   SET status = 'asr_in_progress',
       updated_at = CURRENT_TIMESTAMP
 WHERE video_id = (
     SELECT video_id FROM processing_status
      WHERE status IN ('collected', 'asr_failed')  -- --retry-failed 시 두 값 모두
        AND caption_source IS NULL
      ORDER BY updated_at ASC
      LIMIT 1
   )
   AND status IN ('collected', 'asr_failed')
   AND caption_source IS NULL
RETURNING video_id;
COMMIT;
```

WHERE 절의 status 재확인이 race 방지. RETURNING은 SQLite 3.35+ — B-12 검증.

**Boundary**: B-2 (spec 007 기존 테이블 ALTER), B-4 (spec 011 pair_checkpoint와 status 흐름 연계).

---

## E-9. QualityResultsV4 + ASRQualityFlags (확장)

기존 spec 007 `quality_results` 테이블 + v4 신규 컬럼.

**SQLite v4 ALTER**:

```sql
ALTER TABLE quality_results ADD COLUMN asr_quality_flags TEXT;  -- JSON 직렬화
```

**JSON 페이로드 schema (Pydantic)**:

```python
class AsrQualityFlags(BaseModel):
    """Extensible ASR quality flag set (FR-018).

    Stored as JSON-serialized TEXT in quality_results.asr_quality_flags.
    """
    hallucination_repeat: bool = False
    vad_over_truncated: bool = False
    language_mismatch: bool = False
    short_segments_excess: bool = False
    silence_hallucination: bool = False
    compression_ratio_violations: int = 0  # 임계 초과 세그먼트 카운트

    model_config = {"extra": "allow"}  # 향후 flag 추가 시 schema-less 호환
```

**Lifecycle**:
- 생성: ASR 직후 후처리(`services/asr.py`)에서 6종 flag 측정 후 JSON 직렬화하여 row UPDATE.
- 갱신: 동일 video_id 재ASR 시 새 측정으로 덮어쓰기.

**Boundary**: B-2.

---

## E-10. ComparisonResultV4 (확장)

기존 spec 007/011 `comparison_results` 테이블 + v4 신규 컬럼 + 신설 패턴 enum.

**SQLite v4 ALTER**:

```sql
ALTER TABLE comparison_results ADD COLUMN audio_fp_hamming INTEGER;        -- chromaprint hamming distance
ALTER TABLE comparison_results ADD COLUMN audio_fp_best_offset REAL;       -- 최적 정렬 offset (초)
ALTER TABLE comparison_results ADD COLUMN audio_fp_overlap_seconds REAL;   -- 정렬된 overlap 길이 (초)
ALTER TABLE comparison_results ADD COLUMN source_type_pair TEXT;           -- 'asr-asr' | 'api-api' | 'asr-api' | ...
-- reuse_pattern enum 확장은 Python 측 enum만 (CHECK 없음)
```

**Python enum 확장** (`models/reuse_v2.py`):

```python
class ReusePatternLabel(StrEnum):
    WHOLE_SAME_WEEK = "whole-same-week"
    SCATTERED_SAME_WEEK = "scattered-same-week"
    WHOLE_DIFFERENT_WEEK = "whole-different-week"
    SCATTERED_DIFFERENT_WEEK = "scattered-different-week"
    RE_RECORDED_SAME_CONTENT = "re-recorded-same-content"  # v4 신규
    TAIL_UPDATE = "tail-update"                            # v4 신규
```

**source_type_pair 값**: lexically ordered pair — `'asr-asr'`, `'api-api'`, `'asr-api'`(asr이 sorted 먼저), `'manual-asr'`, `'manual-api'`. 비교 대칭 보장.

**Single aggregate score (C-3 deferred)**: `aggregate_suspicion_score` 컬럼 본 spec 미생성. 30일 운영 후 spec follow-up에서 ALTER ADD COLUMN.

**Boundary**: B-2, B-4.

---

## E-11. MatchSpan (spec 011 schema 권위 — 본 spec에서 첫 영속)

시간축 정렬 매칭 구간 — I-6/I-7/I-8 계산 입력 + 보고서 시각화.

**SQLite (master `storage/content_db.py:532-546` schema 권위 — spec 011 P1이 이미 적재한 형태)**:

```sql
CREATE TABLE IF NOT EXISTS match_spans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    comparison_id INTEGER NOT NULL,
    span_index INTEGER NOT NULL,
    start_a_seconds REAL NOT NULL,
    end_a_seconds REAL NOT NULL,
    start_b_seconds REAL NOT NULL,
    end_b_seconds REAL NOT NULL,
    length_seconds REAL NOT NULL CHECK (length_seconds >= 0),
    matched_text_sample TEXT,
    baseline_subtracted INTEGER NOT NULL DEFAULT 0,
    whitelisted INTEGER NOT NULL DEFAULT 0,
    UNIQUE (comparison_id, span_index),
    FOREIGN KEY (comparison_id) REFERENCES comparison_results(id)
);
CREATE INDEX IF NOT EXISTS idx_span_cmp ON match_spans(comparison_id);
```

**보정 노트 (2026-05-13, qa-engineer 발견)**: 본 spec data-model.md 초안에는 spec 007 schema(`pair_id` PK + start/end coordinates)를 기술했으나 실제 master는 spec 011 P1 schema(`id` AUTOINCREMENT + `comparison_id` FK + `span_index`)를 적재한 상태. 본 spec은 master schema를 권위로 채택하고 컬럼 변경 0 — 기존 sample query / JOIN 패턴 모두 유지.

**본 spec 책임**: spec 011 미완 부분이 본 테이블에 row를 처음으로 적재. `services/nc2_matcher.py::collect_match_spans(pair, src_normalized, tgt_normalized) -> list[MatchSpan]`이 정렬 알고리즘(LCS 또는 슬라이딩 윈도우 — spec 011 알고리즘 권위) 결과를 영속. 컬럼 매핑: source/target coordinates → `start_a_seconds`/`end_a_seconds`/`start_b_seconds`/`end_b_seconds`, span_length → `length_seconds`, baseline 적용 시 `baseline_subtracted=1`, Layer D 라벨 시 `whitelisted=1`.

**Boundary**: B-4 (spec 011 알고리즘 + master schema 권위).

---

## E-12. AuditEvent (논리 entity — 8 stage CSV)

audit_writer.py 일반화. 단계별 frozen fieldnames(R-6).

**파일**: `01_collect/{stage}_audit.csv`

**Stage 8종**:

| Stage | Fieldnames (frozen) |
|---|---|
| `takeout_ingest` | `video_id`, `result`, `reason`, `mp4_filename`, `match_confidence`, `score`, `timestamp` |
| `audio_extract` | `video_id`, `result`, `reason`, `input_kind`, `output_path`, `wav_size_bytes`, `elapsed_s`, `timestamp` |
| `transcripts` | `video_id`, `result`, `reason`, `source`, `caption_source_detail`, `timestamp`, `cookies_source` |
| `fingerprint` | `video_id`, `result`, `reason`, `duration_sec`, `fingerprint_input_policy`, `timestamp`, `cookies_source` |
| `normalize` | `video_id`, `result`, `reason`, `input_source`, `normalizer_version`, `timestamp` |
| `analyze` | `pair_id`, `source_video_id`, `target_video_id`, `result`, `reason`, `matching_mode`, `elapsed_s`, `timestamp` |
| `report` | `professor`, `channel`, `result`, `reason`, `format`, `output_path`, `pair_count`, `appendix_count`, `timestamp` |
| `kb_export` | `video_id`, `result`, `reason`, `format`, `output_path`, `byte_count`, `timestamp` |

**`result` 값**: `'success'` | `'skip'` | `'fail'` (spec 012 패턴 그대로).

**`reason` 값** (대표): `'ignored_by_policy'`, `'empty_transcript'`, `'language_mismatch'`, `'mapping_ambiguous'`, `'mapping_resolved_manual'`, `'asr_failed'`, `'retry_claimed'`, `'interrupted_audio_cleanup'`, `'force_skip_existing'`, `'normalizer_unchanged'`.

**Append-only**: atomic tempfile + rename 패턴(spec 012 `audit_writer.py` 기존 로직 그대로). 기존 row 변경 0.

**Boundary**: B-5.

---

## E-13. CrossSpec Boundaries Diff

본 spec이 prior spec과 공유하는 모든 schema 차이를 한 표로 동결한다.

| 테이블/스키마 | spec 007 → spec 012 (master) | spec 013 (본 spec) v4 |
|---|---|---|
| `processing_status` | 기존 8 컬럼, `VALID_PROCESSING_STATUSES` 7값 | + `match_confidence` (TEXT), + `caption_source_detail` (TEXT), enum + `asr_in_progress`, `asr_failed` |
| `quality_results` | Q-001~Q-005 5컬럼 | + `asr_quality_flags` (TEXT JSON) |
| `comparison_results` | I-1~I-5 + suspicion_score + grade + review_status | + `audio_fp_hamming`, `audio_fp_best_offset`, `audio_fp_overlap_seconds`, `source_type_pair`, reuse_pattern enum + `re-recorded-same-content`, `tail-update`. **`aggregate_suspicion_score` 미추가** (C-3 deferred). |
| `audio_fingerprint` (v3) | 5 컬럼 | 변경 0 |
| `match_spans` | spec 007 schema 그대로 | 본 spec에서 첫 영속(spec 011 알고리즘 완성) |
| `pair_checkpoint` | spec 011 schema 그대로 | 변경 0 (nC2 resumable 인프라 그대로 활용) |
| `channel_metadata` | (미존재) | **신규** |
| `video_metadata` | (미존재) | **신규** |
| `fingerprint_hashes` | spec 007 schema | 변경 0 |
| `professor_pool*`, `baseline_corpus`, `phrase_whitelist` | spec 011 schema | 변경 0 (4계층 오탐 방어 입력) |

**v4 migration 멱등성 검증**: `migrate_to_v4` 함수가 `PRAGMA user_version` 을 4로 bump하기 전에 `IF NOT EXISTS` 가드 + `ADD COLUMN` 시 컬럼 존재 체크(SQLite `PRAGMA table_info`)를 수행한다. 같은 DB 두 번 migration 시 no-op.

---

## v4 Migration Sequence

`storage/content_db.py::migrate_to_v4(db_path: Path) -> None`:

```python
def migrate_to_v4(db_path: Path) -> None:
    """Migrate content_reuse.db from v3 → v4. Idempotent.

    Adds: channel_metadata, video_metadata tables.
    Alters: processing_status (+match_confidence, +caption_source_detail),
            quality_results (+asr_quality_flags),
            comparison_results (+audio_fp_*, +source_type_pair).

    Args:
        db_path: Path to content_reuse.db (assumed v3 schema present).

    Raises:
        ValueError: if PRAGMA user_version < 3 (run migrate_to_v3 first).
    """
    with sqlite3.connect(db_path) as conn:
        cur = conn.cursor()
        cur.execute("PRAGMA user_version;")
        version = cur.fetchone()[0]
        if version < 3:
            raise ValueError(f"Expected user_version >= 3, got {version}. Run migrate_to_v3 first.")
        if version >= 4:
            return  # already migrated
        cur.executescript(_V4_SCHEMA_SQL)
        _add_column_if_missing(cur, "processing_status", "match_confidence", "TEXT")
        _add_column_if_missing(cur, "processing_status", "caption_source_detail", "TEXT")
        _add_column_if_missing(cur, "quality_results", "asr_quality_flags", "TEXT")
        _add_column_if_missing(cur, "comparison_results", "audio_fp_hamming", "INTEGER")
        _add_column_if_missing(cur, "comparison_results", "audio_fp_best_offset", "REAL")
        _add_column_if_missing(cur, "comparison_results", "audio_fp_overlap_seconds", "REAL")
        _add_column_if_missing(cur, "comparison_results", "source_type_pair", "TEXT")
        cur.execute("PRAGMA user_version = 4;")
        conn.commit()
```

`_add_column_if_missing(cur, table, col, type_)` 은 `PRAGMA table_info(table)` 로 컬럼 존재 확인 후 없을 때만 ADD COLUMN — 멱등.

---

## Phase 1 데이터 모델 결론

- 신규 SQLite 테이블 2개 (`channel_metadata`, `video_metadata`).
- 기존 SQLite 테이블 3개 ALTER (`processing_status`, `quality_results`, `comparison_results`).
- 신규 파일 entity 3종 (`_ambiguous_mappings.csv`, `_manual_mappings.csv`, `transcripts_normalized/<video_id>.json`).
- 신규 Pydantic 모델 4종 (`ChannelMetadata`, `VideoMetadata`, `AsrQualityFlags`, `TranscriptNormalized`).
- enum 확장 3건 (`VALID_PROCESSING_STATUSES` +2, `ReusePatternLabel` +2, `VALID_MATCH_CONFIDENCES` 신규).
- Audit CSV 8 stage frozen fieldnames 동결.
- Migration 함수 1개 (`migrate_to_v4`).
- 단일 의심 점수(`aggregate_suspicion_score`) 미생성 — C-3 deferred, 30일 후 follow-up amendment에서 ALTER ADD.
