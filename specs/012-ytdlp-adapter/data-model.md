# Phase 1 Data Model: yt-dlp 자막·음원·지문 어댑터

**Spec**: [spec.md](./spec.md) · **Plan**: [plan.md](./plan.md) · **Research**: [research.md](./research.md)

본 문서는 spec X1 의 5 entity + SQLite v3 schema migration + spec 011/010 boundary diff 를 동결한다.

---

## E-1. Transcript

spec 010 형식을 그대로 사용하되 `source` 값 vocabulary 만 확장.

**JSON schema** (`projects/{job-id}/01_collect/transcripts/{video_id}.json`):

```json
{
  "video_id": "tuxscjwiJYs",
  "language": "ko",
  "source": "ytdlp:manual",
  "fetched_at": "2026-05-09T20:11:34+09:00",
  "segments": [
    {"start": 3.3, "end": 7.859, "text": "안녕하세요 홍길동의 교수입니다"},
    {"start": 5.64, "end": 9.599, "text": "2022학년도 1학기"}
  ]
}
```

**Field constraints**:
- `video_id`: YouTube video ID (11자, alnum + `_-`)
- `language`: BCP-47 코드 (현재 `ko` 만, 향후 다국어 확장 가능)
- `source`: enum — `ytdlp:manual` | `ytdlp:auto` | `api` (spec 010 호환, 본 spec에서 첫 두 값 신규 추가)
- `fetched_at`: ISO 8601 timezone-aware (Constitution V — 단일 timezone 표기 금지)
- `segments[].start`, `segments[].end`: float seconds, 3 decimal places
- `segments[].text`: 한국어 + 공백, 길이 0 segment 금지 (srv3_parser 가 보장)

**Lifecycle**:
- 생성: `srv3_to_transcript_json()` 호출 직후 atomic write (`*.json.tmp` → rename)
- 갱신: `--force` 플래그 시에만, 같은 atomic write
- 삭제: 운영자 수동 only (CLI 미제공)

**B-X1-1 boundary**: spec 010 transcript JSON 형식 권위. 본 spec은 새 `source` 값 두 개만 추가, 기존 필드 변경 0.

---

## E-2. Audio Temp File

음원 임시 파일 — extract → fingerprint → delete lifecycle.

**Path** (`projects/{job-id}/01_collect/audio_temp/{video_id}.mp3`):

| Attribute | Value | Source |
|---|---|---|
| `format` | mp3 | yt-dlp `--audio-format mp3` |
| `sample_rate` | 22050 Hz | `--postprocessor-args "ffmpeg:-ar 22050 -ac 1"` |
| `channels` | 1 (mono) | 동상 |
| `bitrate` | 128 kbps (자동) | `--audio-quality 128K` |
| `duration` | 영상 원본 동일 | ffprobe 일치 검증 |

**Lifecycle invariants** (FR-009, SC-004):
- 정상 종료: 명령 종료 시점에 디렉터리 잔재 0건
- 비정상 종료(SIGINT/SIGTERM): `tube-scout collect *` 다음 실행 시 시작 시점 `audio_temp/` 정리 + audit-log "interrupted" 영상은 재처리
- `tube-scout` 외 다른 프로세스가 만든 파일 — 의심 actionable 메시지 + 자동 삭제 거절 (운영자 수동 cleanup 안내)

**Persistence forbidden** (Constitution V): 본 entity는 영속 0. 향후 spec에서도 audio file 영속 도입 금지 (Constitution V 위반).

---

## E-3. Audio Fingerprint

chromaprint 음향 지문 영속 — spec Y(미래) read-only consume.

**SQLite v3 DDL** (`projects/{job-id}/02_analyze/content/content_reuse.db`):

```sql
CREATE TABLE IF NOT EXISTS audio_fingerprint (
    video_id     TEXT PRIMARY KEY,
    fingerprint  BLOB NOT NULL,                      -- chromaprint base64 ASCII bytes
    duration     REAL NOT NULL,                     -- seconds, ffprobe-verified
    extracted_at TEXT NOT NULL,                     -- ISO 8601 timezone-aware
    source       TEXT NOT NULL DEFAULT 'fpcalc:1.6.0',  -- 알고리즘·버전 (forward compat)
    FOREIGN KEY (video_id) REFERENCES videos(video_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_audio_fp_extracted_at
    ON audio_fingerprint(extracted_at);

PRAGMA user_version = 3;
```

**Field constraints**:
- `video_id`: spec 011 `videos` 테이블 PK 참조 (FK 강제)
- `fingerprint`: chromaprint b64 ASCII (예: `b"AQA-rVMSRUkiJdmEjzoq..."`). spike 측정 33분 → 65,455 bytes / 28분 → 56,408 bytes (~2 KB/min)
- `duration`: ffprobe 결과와 ±1초 일치 (fpcalc DURATION 정수)
- `extracted_at`: ISO 8601 timezone-aware (Constitution VII 일관성)
- `source`: 향후 다른 알고리즘 도입 시 (예: `lsh:v1`) 추가 가능 — spec X1은 `fpcalc:1.6.0` 단일 값

**Migration** (idempotent):
```python
def migrate_to_v3(db_path: Path) -> None:
    """Add audio_fingerprint table and bump user_version to 3.

    Safe to call multiple times (CREATE TABLE IF NOT EXISTS).
    Pre-condition: db at version 2 (spec 011 schema).
    Post-condition: user_version == 3, audio_fingerprint table exists.
    """
```

**Storage estimate**: 22 채널 × 4,000 영상 × 평균 25분 × ~2 KB/min ≈ **5.5 GB** (단일 SQLite 파일, Constitution V 준수).

**B-X1-2 boundary**: spec 011 v2 schema(videos / segments / matches 등) 변경 0, 신규 테이블 1개 추가만.
**B-X1-3 boundary**: spec Y(미래)는 본 entity를 read-only consume — schema 동결 (필드 삭제·이름 변경 금지). spec Y가 LSH bucket 등 보조 테이블 추가 시 ALTER로만.

---

## E-4. Cookies Source

cookies 인증 출처 — runtime 표현, 영속 없음.

```python
@dataclass(frozen=True)
class CookiesSource:
    """Cookies authentication source resolution result.

    Attributes:
        kind: One of 'browser' | 'file'.
        browser: Browser name when kind == 'browser' (e.g., 'brave').
        path: File path when kind == 'file'.
    """
    kind: Literal["browser", "file"]
    browser: str | None = None
    path: Path | None = None
```

**Resolution chain** (FR-017, R-6):
1. CLI flag `--cookies-browser <name>` → kind="browser", browser=<name>
2. CLI flag `--cookies-file <path>` → kind="file", path=<path>
3. 환경변수 `TUBE_SCOUT_COOKIES_FILE` → kind="file", path=$TUBE_SCOUT_COOKIES_FILE
4. 환경변수 `TUBE_SCOUT_COOKIES_BROWSER` → kind="browser", browser=$TUBE_SCOUT_COOKIES_BROWSER
5. 디폴트 `kind="browser", browser="brave"` (spike 검증)
6. brave 디크립션 실패 시 자동 폴백: 디폴트 경로 `~/.config/tube-scout/cookies.txt`(0600) 존재 시 kind="file"
7. 모두 부재 시 actionable 거절

**B-X1-6 boundary**: agenix 환경변수 참조 호환. cookies file 경로 `0600` 권한 강제 (생성 시 검증).

---

## E-5. Audit Record

처리 감사 — CSV 영속, 운영자 컴플라이언스 검증용.

### Transcripts audit (`projects/{job-id}/01_collect/transcripts_audit.csv`):

| 컬럼 | 타입 | 값 |
|---|---|---|
| `video_id` | str (11) | YouTube video ID |
| `result` | enum | success / skip / fail |
| `reason` | enum | captured / skip_existing / no_captions_available / rate_limit / cookies_expired / live_or_premiere / network_failure / interrupted |
| `source` | enum or null | ytdlp:manual / ytdlp:auto / api / null(fail/skip) |
| `timestamp` | ISO 8601 tz | 처리 시각 |
| `cookies_source` | enum | brave / file / n/a (api source) |

### Fingerprint audit (`projects/{job-id}/01_collect/fingerprint_audit.csv`):

| 컬럼 | 타입 | 값 |
|---|---|---|
| `video_id` | str (11) | YouTube video ID |
| `result` | enum | success / skip / fail |
| `reason` | enum | captured / skip_existing / too_short / audio_decode_failed / fpcalc_failed / rate_limit / interrupted |
| `duration_sec` | float or null | ffprobe duration (success/skip 시), null(fail) |
| `timestamp` | ISO 8601 tz | 처리 시각 |
| `cookies_source` | enum | brave / file |

**Append-only**: 매 명령 실행 시 CSV에 append (header는 파일 생성 시 1회만). 운영자 grep / pandas 분석 가능.

**Rotation**: spec X1 scope 외 — 운영자가 cron `logrotate` 또는 별도 cleanup으로 처리. 본 spec은 unbounded growth 방지 책임 0 (job-id 별 디렉터리이므로 자연 분리됨).

---

## Boundary diff vs spec 010, 011

| Entity / 자산 | spec 010 | spec 011 | spec X1 (본 spec) |
|---|---|---|---|
| `transcripts/{vid}.json` 형식 | 권위 (생성) | read-only consume | 동일 형식 생성, `source` 값 2개 신규 (`ytdlp:manual`, `ytdlp:auto`) |
| `content_reuse.db` v2 schema | 미사용 | 권위 (생성) | v3 ALTER 추가 (`audio_fingerprint` 테이블만), v2 변경 0 |
| `services/fingerprint.py` (텍스트 SHA) | 미사용 | 권위 (생성) | 변경 0, 신규 module 별도 (`audio_fingerprint.py`) — B-X1-9 격리 |
| `01_collect/transcripts_audit.csv` | 미생성 | 미사용 | 신규 생성 (spec 009 audit CSV 컨벤션 정합) |
| `01_collect/fingerprint_audit.csv` | 미생성 | 미사용 | 신규 생성 |
| `01_collect/audio_temp/` 임시 디렉터리 | 미사용 | 미사용 | 신규, lifecycle 0 (영속 금지) |

---

## Validation rules

본 entity 들이 강제하는 도메인 규칙:

**RV-1**: `Transcript.segments` 가 비어있으면 transcript JSON 생성 금지 — audit-log "no_captions_available" 만 기록.

**RV-2**: `Transcript.source == "ytdlp:manual"` 이면 `srv3_parser` 가 yt-dlp `--write-subs` 다운로드 결과를 파싱한 결과여야 함 (yt-dlp 메타 검증).

**RV-3**: `AudioFingerprint.duration` 과 영상 메타데이터 `videos.duration_sec` (spec 003) 의 차이가 1초 이내여야 함 — 차이 시 audit-log "duration_mismatch" + 지문 저장 거절.

**RV-4**: `AudioFingerprint.fingerprint` 의 b64 디코드 결과가 16 bytes 미만이면 거절 (chromaprint 빈 결과 sanity).

**RV-5**: `AuditRecord.timestamp` 은 timezone-aware 이어야 함 (Constitution VII 일관성).

**RV-6**: `audio_temp/` 디렉터리에 명령 종료 시점 잔재가 있으면 SC-004 위반 — 통합 테스트가 잔재 0 검증.

**RV-7**: srv3 → spec 010 transcript JSON 변환 시 동일 / 중복 timestamp 의 segment 는 **그대로 보존** (dedup 책임 0). spec 011 (`reuse-fullstack-subtitle`) 파이프라인이 dedup·정규화 책임을 가짐 — 본 spec 은 srv3 원본 시간순서를 유지한다.

---

## State transitions

### Transcript fetch (P1)

```
[no transcript file]
    │
    ├── --source ytdlp + cookies OK + manual 트랙 발견
    │       └─→ [transcript JSON 생성, source="ytdlp:manual"]
    ├── --source ytdlp + cookies OK + manual 부재 + auto 트랙 발견
    │       └─→ [transcript JSON 생성, source="ytdlp:auto"]
    ├── --source ytdlp + cookies OK + 트랙 모두 부재
    │       └─→ [audit "no_captions_available", transcript 없음]
    ├── --source ytdlp + cookies 실패
    │       └─→ [audit "cookies_expired" or "rate_limit", transcript 없음, 채널 종료]
    └── --source api (spec 010 흐름)
            └─→ [spec 010 권위 흐름, source="api"]

[transcript file 존재]
    │
    ├── --force 미사용
    │       └─→ [audit "skip_existing"]
    └── --force
            └─→ 위 흐름과 동일 (덮어쓰기)
```

### Audio fingerprint (P2)

```
[no audio_fingerprint row]
    │
    ├── duration < 30s
    │       └─→ [audit "too_short", DB 변경 0]
    ├── duration ≥ 30s + 음원 추출 OK + fpcalc OK
    │       └─→ [DB INSERT, audit "captured", 음원 즉시 삭제]
    ├── 음원 추출 실패 (인코딩 미지원)
    │       └─→ [audit "audio_decode_failed", DB 변경 0, 음원 정리]
    └── fpcalc 실패
            └─→ [audit "fpcalc_failed", DB 변경 0, 음원 정리]

[audio_fingerprint row 존재]
    │
    ├── --force 미사용
    │       └─→ [audit "skip_existing"]
    └── --force
            └─→ 위 흐름과 동일 (덮어쓰기, INSERT OR REPLACE)
```

---

## References

- spec 010 transcript JSON 형식 — `specs/010-prefer-captions-resume/spec.md`
- spec 011 v2 schema — `specs/011-reuse-fullstack-subtitle/spec.md` + `src/tube_scout/storage/content_db.py:migrate_to_v2()`
- spec 003 alias resolver — `src/tube_scout/services/professor_resolver.py` (alias → channel_id)
- spec 009 audit CSV 컨벤션 — `transcripts_audit.csv` (`specs/009-runtime-auth-fix/spec.md`)
- chromaprint b64 형식 — AcoustID guide
- spike 측정 — `_workspace/spike/ytdlp_feasibility.md`
