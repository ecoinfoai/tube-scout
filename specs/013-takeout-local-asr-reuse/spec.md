# Feature Specification: Takeout 기반 로컬 ASR + 강의 영상 재사용 판정 + 자막 KB Export

**Feature Branch**: `013-takeout-local-asr-reuse`
**Created**: 2026-05-13
**Status**: Draft
**Target Release**: v0.5.0 (운영자 결정 — Phase 1~4 단위 머지, 최종 Phase 4에서 v0.5.0 release)
**Idea Doc**: `idea/idea-2026-05-12-takeout-knowledge-base.md`
**선행 결정**:
- `memory/project_takeout_pivot_20260512.md` — yt-dlp 영구 폐기, Google Takeout export 전환 (NON-NEGOTIABLE)
- `memory/feedback_external_comms_no_takeout.md` — 외부 커뮤니케이션(YouTube/Google 등)에는 Takeout 사실 비공개
**Input**: User description: "Takeout-based local ASR + lecture-video content-reuse detection + knowledge-base transcript export"

---

## Clarifications

### Session 2026-05-13

- Q: Takeout 원본 mp4 · WAV · 자막 JSON 의 데이터 보존 정책은? → A: mp4 영구 보존(acquisition 원본 — Takeout 재신청 비용 큼), WAV 비영구(통합 모드 즉시 삭제, `--keep-audio` 시만 보존), raw/normalized 자막 JSON 영구 보존(분석·KB export 재실행 입력)
- Q: Audit logging surface와 format은? → A: spec 012 master의 `audit_writer` 인프라(append-only CSV, frozen fieldnames) 계승·확장. 단계별 분리: `01_collect/{stage}_audit.csv` (stage ∈ {`takeout_ingest`, `audio_extract`, `transcripts`, `fingerprint`, `normalize`, `analyze`, `report`, `kb_export`}). Phase 4에서 audit_writer는 yt-dlp surface와 분리되어 cross-stage 일반화 모듈로 재배치.
- Q: 단일 의심 점수(aggregate suspicion score) 공식은? → A: Multi-axis 한시 운영 후 가중 합산 후속 commit. Phase 3 출시 시점에는 single aggregate score 없이 multi-axis(`--sort-by <metric>`)로 보고서 정렬, `--appendix-threshold` 도 single-metric 임계(예: `--appendix-threshold-i2-cosine 0.85`) 형태. 30일 누적 후 가중치 합산 공식을 spec follow-up에서 commit, 그 시점에 통합 `--appendix-threshold <0..1>` 로 전환.
- Q: 장시간 작업(19,900쌍 분석 / 200영상 ASR) 진행 상황 표시 형식은? → A: 환경 자동 감지(`sys.stdout.isatty()`). TTY 환경에선 rich.progress 진행률 바(현재 video_id / pair_index, ETA, 완료 비율), 비-TTY(cron · nohup · ssh detach) 환경에선 structured stdout log line(`[stage] video_id N/total elapsed=Xs ETA=Ys`)을 매 영상 또는 매 N쌍 주기로 출력.
- Q: `--retry-failed` 시 워커 풀의 상태 전이는? → A: `asr_failed` → `asr_in_progress` 직접 atomic 전이. `--retry-failed` 플래그는 단지 워커의 claim predicate를 `status IN ('collected','asr_failed') AND caption_source IS NULL` 로 확장하는 단일 변경이며, 별도 state reset 단계는 없다. 두 워커가 동시에 retry 시도해도 단일 SQLite 트랜잭션이 단일 워커만 성공시킨다(멱등).

---

## User Scenarios & Testing *(mandatory)*

### User Story 1 — 교수 단위 M-nC2 강의 영상 재사용 판정 보고서 (Priority: P1)

**Personas**:
- **Actor (CLI runner)**: 운영자 = DX지원센터장 / RISE 사업단 부단장. 4단계 CLI 명령을 실행하고 ambiguous 매핑 큐·화이트리스트를 편집한다.
- **Audience (Report reader)**: 교무 검토자 = 교무팀 행정직원. CLI를 직접 실행하지 않으며 운영자가 생성·전달한 PDF/HTML 보고서 한 부만 받아 어느 영상 쌍을 들여다볼지 1차 판단한다(SC-006의 대상).

운영자가 Google Takeout으로 export한 자교 채널의 한 교수 영상 풀(예: 정광석 교수 200여 개)에 대해, 모든 영상 쌍(nC2 ≈ 19,900쌍)을 자막·시간축·음원 지문 신호로 비교하여, 의심 상위 항목을 정량 근거와 반론(오탐 방어 적용 내역)이 함께 담긴 한 부의 PDF/HTML 보고서로 받는다. 교무 검토자는 이 한 부의 보고서로 어느 영상 쌍을 우선 들여다볼지 판단할 수 있다.

**Why this priority**: 본 idea의 1차 가치 명제. 자교 강의 영상 재사용 판정은 RISE 사업단 운영 책임의 핵심이고, spec 007/011/012 흐름이 누적된 결과를 운영 환경에서 실제로 사용 가능한 산출물로 마감하는 단일 가치 슬라이스. 본 스토리만 구현해도 학과 단위 운영 검토가 시작 가능하므로 MVP 자격.

**Independent Test**: 운영자가 한 채널 alias(예: `nursing`)와 한 교수명을 인자로 보고서 명령을 실행하면, 그 교수의 영상 풀에 대해 M-nC2 비교가 수행되고 한 부의 PDF/HTML 보고서가 출력된다. 본문에는 의심 등급 분포·top-K 목록·패턴별 통계·4계층 오탐 방어 적용 내역이, 부록에는 임계 이상 의심 쌍의 1:1 상세가 포함된다. 본 보고서는 단정적 판정이 아닌 "검토 우선순위" 형태로 표현된다.

**Acceptance Scenarios**:

1. **Given** Takeout export가 디스크에 압축 해제되어 있고 채널 alias `nursing` 이 등록되어 있을 때, **When** 운영자가 `collect takeout` → `collect process-audio` → `analyze content-reuse` → `report content-reuse` 4단계를 차례로 실행하면, **Then** 한 교수 단위의 M-nC2 PDF 보고서 1부와 HTML 보고서 1부가 생성되고, SQLite에는 채널 메타·영상 메타·자막 정규화 결과·8지표 비교 결과·음원 지문 비교 결과·패턴 분류가 모두 영속된다.
2. **Given** 같은 Takeout 디렉터리에 대해 ingestion이 이미 한 번 실행된 상태일 때, **When** 동일 Takeout 디렉터리 또는 새 part(`3-002`)를 추가 ingestion하면, **Then** 부작용 없이 새 영상만 누적되고 기존 row는 변경되지 않는다(idempotent). 같은 part 재실행은 no-op.
3. **Given** 매핑 결과 중 일부가 ambiguous로 분류되었을 때, **When** 운영자가 `01_collect/_ambiguous_mappings.csv` 를 편집하여 한 행에 한 video_id로 정리한 뒤 ingestion을 재실행하면, **Then** 운영자 결정이 그대로 반영되고 자동 매핑 단계는 우회된다.
4. **Given** 비공개 영상이 ASR 처리 도중 워커 1개가 실패할 때, **When** `processing_status` 가 `asr_failed` 로 기록된 뒤 운영자가 `--retry-failed` 로 재실행하면, **Then** 실패 row만 재시도되고 나머지 영상은 영향받지 않는다.
5. **Given** 보고서 본문이 생성될 때, **When** 운영자가 텍스트 톤을 점검하면, **Then** "재활용 확정", "위반" 등 단정적 라벨이 한 건도 없고 모든 의심 표현은 "의심 근거", "검토 우선순위 상위", "주의 필요" 같은 보류형으로 일관된다.
6. **Given** 보고서 부록 임계가 명시되지 않은 상태로 운영 첫 30일 구간일 때, **When** 보고서를 생성하면, **Then** 부록에는 임계 컷이 적용되지 않고 분포 히스토그램이 함께 출력되어 운영자가 임계 기준을 직접 결정할 수 있는 자료를 제공한다.

---

### User Story 2 — 선별 영상 자막 텍스트 export로 외부 Knowledge Base 입력 생성 (Priority: P2)

운영자가 자신의 강의나 우수 강의 영상 ID를 지정하여 자막 JSON을 깨끗한 텍스트 파일(txt / md / jsonl)로 받아, 외부 knowledge base 도구(검색 인덱스 / RAG / LLM 미세조정)의 입력으로 그대로 사용한다. 자막 출처(ASR / YouTube Data API caption)와 무관하게 동일한 export 도구로 처리된다.

**Why this priority**: 본 idea의 2차 가치 명제. P1 파이프라인이 산출하는 자막 자산을 재사용하므로 추가 데이터 수집 없이 한 CLI 명령으로 끝나는 단순 변환. P1과 독립적으로 테스트·출시 가능하지만, 가치 명제로서는 P1보다 narrower(특정 영상 선별 후 외부 도구로 넘기는 보조 경로).

**Independent Test**: 운영자가 단일 video_id를 인자로 export 명령을 실행하면 해당 영상의 자막이 한 개의 텍스트 파일로 떨어지고, 채널 alias를 인자로 bulk 명령을 실행하면 채널 전체 자막이 한 디렉터리에 영상별 파일로 떨어진다. 산출물은 외부 도구가 그대로 읽을 수 있는 UTF-8 평문(BOM 없음).

**Acceptance Scenarios**:

1. **Given** ASR 또는 API caption 흐름으로 `transcripts/<video_id>.json` 이 생성된 상태일 때, **When** 운영자가 `transcript export --video-id <id> --format txt --output <path>` 를 실행하면, **Then** 타임스탬프가 제거된(또는 `--keep-timestamps` 시 보존된) 깨끗한 텍스트 파일이 지정 경로에 출력되고 파일 인코딩은 UTF-8 (BOM 없음)이다.
2. **Given** 한 채널의 자막이 50편 분량으로 누적된 상태일 때, **When** 운영자가 `transcript export-bulk --channel <alias> --output-dir <dir>` 를 실행하면, **Then** 50개의 텍스트 파일이 한 디렉터리에 영상별로 떨어지고 각 파일 이름은 video_id를 포함하여 외부 도구의 인덱싱이 가능하다.
3. **Given** 같은 video_id의 자막 출처가 ASR과 API caption 두 가지로 따로 존재할 수는 없는 정책일 때(§FR-024 단일 출처 규칙), **When** export 명령이 호출되면, **Then** 자막 출처가 무엇이든 동일한 export 결과가 나오고 운영자에게 출처가 표시된다.

---

### User Story 3 — 자교 운영 적합성을 위해 yt-dlp 레거시 완전 제거 (Priority: P3)

운영자(공기관·대학 RISE 사업단 부단장)가 코드베이스에서 yt-dlp 관련 소스·CLI·테스트·devShell 의존성·문서를 완전히 제거한다. 이는 yt-dlp 사용이 공기관 운영 환경에 적합하지 않다는 운영자 판단(2026-05-13)에 따른 영구 결정이며, `_archive/` 보존 없이 master에서 완전 삭제한다.

**Why this priority**: 컴플라이언스 안전판. P1·P2의 가치는 본 스토리 없이도 성립하지만, 코드베이스에 yt-dlp 경로가 잔존하면 운영자 정책과 실제 코드가 어긋난다. 마지막 Phase로 두는 이유는 P1 파이프라인이 안정적으로 동작함이 확인된 뒤에 안전하게 제거하기 위함.

**Independent Test**: 운영자가 Phase 4 머지 후 코드베이스를 검색하면 `ytdlp_adapter`, `ytdlp_errors`, `srv3_parser`, `--source ytdlp` 등 yt-dlp 관련 식별자가 한 건도 발견되지 않는다. devShell · pyproject 의존성에서도 yt-dlp 흔적이 사라진다. P1·P2 회귀 테스트는 모두 통과 상태를 유지한다.

**Acceptance Scenarios**:

1. **Given** Phase 4 머지가 끝난 상태일 때, **When** 운영자가 코드베이스를 grep으로 점검하면, **Then** `ytdlp` / `yt-dlp` / `--source ytdlp` 식별자가 src · tests · docs · devShell 어느 곳에서도 검색되지 않는다(README · CLAUDE.md `Active Technologies` 갱신 포함).
2. **Given** spec 012 흐름에 의존하던 회귀 테스트가 존재할 때, **When** Phase 4 머지 후 전체 테스트 스위트를 실행하면, **Then** spec 012 전용 테스트는 함께 제거되고 spec 007/010/011/본 spec 테스트는 모두 통과한다.
3. **Given** 운영자가 코드 변경 이력을 추적할 때, **When** git history를 조회하면, **Then** 삭제 commit이 단일 commit 또는 명확히 구분된 commit 집합으로 남아 향후 회고가 가능하다(`_archive/` 보존은 채택하지 않음).

---

### Edge Cases

**Ingestion 단계**:
- 같은 video_id가 Takeout 분할 part 여러 곳에 등장 — ingestion은 멱등이어야 하며 마지막 part의 메타로 덮어쓰지 않고 처음 들어온 메타를 권위로 유지한다.
- mp4 파일명이 OS 255자 제한에 의해 제목 끝부분이 절단된 상태 — 정규화 매칭(가중치 +30)과 duration(±1초, 가중치 +25)으로 식별. 그래도 미달이면 ambiguous 큐.
- 두 video_id의 제목이 동일(예: 같은 강의를 한 해 차이로 재업로드) — duration · 메타 timestamp · 운영자 manual override CSV로 분기. 자동 매핑이 결정할 수 없으면 ambiguous.
- 메타데이터 CSV에 row가 있는데 mp4 파일이 다른 part에 있어 현재 디렉터리에는 부재 — `status='collected'` 로 row만 등록하고 audio·STT·지문 단계에서는 자동 스킵, 추후 mp4가 들어오는 part가 ingestion되면 재개.
- 압축 해제 · 복사 · 외장하드 동기화 과정에서 mp4 mtime이 손상 — mtime은 보조 신호(가중치 +5)로만 사용하므로 단독 실패 요인이 되지 않는다.
- Takeout export에 `댓글.csv`, `시청 기록`, `검색 기록` 카테고리 포함 — ingestion 어댑터는 명시적으로 무시하고 audit-log에 "ignored_by_policy" 사유와 함께 기록.

**Audio extract / STT 단계**:
- 동일 video_id의 wav가 이미 캐시에 존재 — 재추출 없이 그대로 재사용(멱등).
- ASR 워커가 영상 처리 도중 충돌 — `processing_status='asr_in_progress'` 가 남는다. 운영자가 stale 상태를 확인하고 `--retry-failed` 로 재시작.
- Whisper가 무음 구간에서 "구독과 좋아요 부탁드립니다" 같은 학습 잔재를 반복 생성 — VAD + condition_on_previous_text=False + compression_ratio_threshold=2.4 + no_speech_threshold=0.6 기본 강제로 차단, 동일 텍스트 3회 이상 반복은 `asr_quality_flags.hallucination_repeat=true` 로 기록.
- 강제 언어 `ko` 인데 영어 발화 비중이 높은 영상 — `asr_quality_flags.language_mismatch=true` 기록, 자막은 출력하되 보고서에서는 품질 플래그가 표시된다.
- 0.5초 미만 세그먼트 비중이 임계 초과 — `asr_quality_flags.short_segments_excess=true` 기록.
- A6000 워커 풀에서 두 프로세스가 같은 video_id를 동시에 claim 시도 — SQLite 트랜잭션에서 `status='collected' AND caption_source IS NULL` 조건 + `UPDATE … RETURNING` 패턴으로 단일 워커만 성공.

**분석 단계**:
- 200영상 = 19,900쌍 처리 중 운영자가 Ctrl+C — `pair_checkpoint` 테이블이 다음 실행 시 이어붙기를 보장.
- 한 영상에 자막이 ASR 출처이고 다른 영상은 API caption 출처(이기종 비교) — 비교 전에 Text Normalizer가 강제 실행되어 출처 차이를 흡수, `comparison_results.source_type_pair='asr-api'` 로 메타 기록.
- 임계 이상 의심 쌍이 5,000개로 부록이 비대해짐 — 부록 임계 옵션 또는 분포 히스토그램으로 운영자가 직접 컷오프 설정.
- 음원 지문이 자막 신호와 정반대 결과(자막은 동일 / 음원은 다름) — `re-recorded-same-content` 패턴으로 분류.
- I-8 정렬 밀도가 영상 전반부 1.0 · 후반부 0.0 — `tail-update` 패턴으로 분류, 시간축 프로필 차트 동봉.

**보고서·KB export 단계**:
- 한 교수의 영상이 0개 — actionable 메시지("Professor '<name>' has no videos in channel '<alias>'. Check `videos_meta.json` or alias mapping.") 후 종료(0이 아닌 exit).
- 자막 JSON에 세그먼트가 0개(완전 무음 영상) — export 명령은 빈 텍스트 파일을 생성하되 audit에 "empty_transcript" 사유 기록.
- 동일 video_id에 ASR과 API caption이 모두 존재(정책 위반 상태) — § FR-024 단일 출처 정책에 따라 actionable 메시지로 운영자에게 결정 요청 후 종료. 자동 우선순위 룰은 도입하지 않음.

**기타**:
- 운영자가 데이터 작업 디렉터리를 외장 디스크로 이전 — `mp4_relative_path` 가 작업 디렉터리 기준 상대 경로이므로 DB는 손대지 않고 CLI `--takeout-dir` 인자만 새 경로로 바꿔 실행. 심볼릭 링크 방식은 POSIX 호환 OS에서만 검증.
- spec 012 흐름과 본 spec 흐름이 Phase 4 이전 시기 양립 — 운영자는 본 spec CLI(`collect takeout` / `collect process-audio`)만 사용해야 하며 spec 012 CLI(`--source ytdlp`)는 사용하지 않는다(메모리 `feedback_account_isolation_policy` 잔존 정책).

---

## Cross-Spec Boundaries *(Constitution VII — NON-NEGOTIABLE)*

본 spec이 prior spec · 외부 시스템 · agenix 변수 · OAuth 토큰 · 출력 디렉터리 컨벤션 · 식별자 · 에러 포맷 · 공유 서비스 함수와 공유하는 모든 경계를 1급 산출물로 동결한다. 각 항목은 (1) 이전 측 보장, (2) 본 spec 가정·신규 생산, (3) 검증 시나리오 매핑을 명시한다. 동일 표가 `plan.md` §Cross-Spec Boundaries에도 보존되어 plan/tasks 단계에서 검증 진입점이 직접 매핑된다.

| ID | 경계 | 이전 측 보장 (prior) | 본 spec 가정 / 신규 생산 | 검증 시나리오 |
|---|---|---|---|---|
| **B-1** | spec 003 alias resolver | 자교 채널 alias → channel_id 매핑이 `tokens/channels.json` 또는 `services/professor_resolver.py`에 등록. | `collect takeout --channel <alias>` 진입 시 alias 검증, 미등록 시 actionable 영문 메시지 후 거절. | User Story 1 Acceptance Scenario 1 (alias `nursing` 사용) + tests/integration/test_takeout_ingest_e2e.py |
| **B-2** | spec 007 `content_reuse.db` v2 schema | `processing_status`, `fingerprint_hashes`, `comparison_results`(I-1~I-5), `quality_results`, `match_spans`, `pair_checkpoint`, `professor_pool` 등 기존 테이블 권위. | v4 migration이 기존 테이블 ALTER (`processing_status.match_confidence` / `.caption_source_detail`, `quality_results.asr_quality_flags`, `comparison_results.audio_fp_*` / `.source_type_pair`) — 기존 row preserve, 기존 컬럼 변경 0. | tests/integration/test_v4_migration.py (v3 DB → v4 적용 → 기존 row 무결성 검증) |
| **B-3** | spec 010 transcript JSON schema | `01_collect/transcripts/<video_id>.json` 형식 (`segments[].start`, `.end`, `.text`, `video_id`, `language`, `source`, `fetched_at`). | ASR 출력과 captions_api 출력 모두 동일 schema 따름. 본 spec은 `source` enum 신설 없음 — `whisper` 는 spec 010이 이미 보유. | tests/contract/test_transcript_json_schema.py |
| **B-4** | spec 011 분석 인프라 (`nc2_matcher`, `pair_checkpoint`, `match_spans`, `layer_defense`, `phrase_whitelist`, `baseline_corpus`, `pattern_classifier`, `time_axis_indicators`) | 부분 구현된 모듈들(spec 011 P1 미완). 시그니처는 spec 011 contracts/ 에 동결. | I-6/I-7/I-8 시간축 지표 함수 완성, M-nC2 매칭 모드 완성, 4계층 오탐 방어 완성, 4패턴 분류 + 신설 2패턴(re-recorded / tail-update) 추가. `match_spans` 테이블에 시간축 정렬 결과 영속. | tests/integration/test_nc2_analysis_full.py (9 영상 → 36쌍 end-to-end) |
| **B-5** | spec 012 `services/audit_writer.py` | spec 012가 `transcripts_audit.csv` + `fingerprint_audit.csv` 두 단계 audit를 frozen fieldnames + append-only로 운영. 컬럼 규약: `video_id`, `result` (success/skip/fail), `reason` (machine-readable identifier — `ignored_by_policy`, `empty_transcript`, `language_mismatch` 등), 단계별 추가 필드. | 단계 8종(`takeout_ingest`, `audio_extract`, `transcripts`, `fingerprint`, `normalize`, `analyze`, `report`, `kb_export`) 각각의 frozen fieldnames 추가. spec 012 컬럼 규약 그대로 계승 — `result` + `reason` 패턴이 본 spec 8 stage 전체에 적용. Phase 4 yt-dlp 코드 삭제 시 `audit_writer.py`는 cross-stage 일반화 모듈로 유지(삭제 금지) — `services/audit_writer.py` 위치 그대로. | tests/contract/test_audit_writer_v2_contract.py + tests/integration/test_audit_log_pipeline.py |
| **B-6** | spec 012 `audio_fingerprint` 테이블 (SQLite v3) | `migrate_to_v3()` 완료, `insert_audio_fingerprint`/`get_audio_fingerprint` 함수 권위. | 읽기·쓰기 변경 없이 재사용. v4 migration은 본 테이블 건드리지 않음 — 신규 테이블 + 기존 테이블 ALTER만. | tests/integration/test_v3_to_v4_idempotent.py |
| **B-7** | spec 012 `services/audio_fingerprint.py` `extract_chromaprint_fingerprint(audio_path, length_seconds=0)` | mp4·wav 입력 모두 처리 가능, 9개 takeout mp4 실측 검증 완료(2026-05-12). | `fingerprint_input_policy ∈ {original_mp4, wav_16k, wav_22k}` 셋 모두 본 함수 단일로 처리. Phase 1 실측 후 기본값 commit. | tests/integration/test_fingerprint_input_policy_compare.py (Phase 1) |
| **B-8** | spec 012 `services/srv3_parser.py`, `services/ytdlp_adapter.py`, `services/ytdlp_errors.py` | 현재 master 운영, deprecated. | tasks Phase 1~3(= idea Phase 1~3) 동안 코드베이스에 공존(import만 발생, 본 spec 코드 흐름에서는 호출 0건). tasks Phase 5 / idea Phase 4 에서 완전 삭제(FR-046). | tests/integration/test_phase4_legacy_removal.py (tasks Phase 5) |
| **B-9** | spec 006 report bundle 인프라 (`reporting/`, jinja2 템플릿) | bundle 생성기, CSS, HTML→PDF (weasyprint) 경로 권위. | 신규 템플릿 `professor_nC2_report.html` 추가, multi-axis 정렬 + per-metric 분포 히스토그램 + top-K 목록 + 부록 1:1 페이지. 기존 보고서 템플릿(spec 004/006) 영향 0. | tests/integration/test_professor_nc2_report.py |
| **B-10** | spec 009 OAuth 토큰 (`~/.config/tube-scout/tokens/`) | 0600, agenix 무관(운영자 관리). spec 009의 `auth.py` / `auth_device_flow.py` API 권위. | 공개 영상 caption 다운로드 시 spec 009 토큰을 그대로 재사용. Takeout 외 외부 API 호출은 본 경로뿐. captions_api 실패 시 audit-log + 다음 영상 진행. | tests/integration/test_captions_api_with_oauth.py |
| **B-11** | spec 008 admin web UI | starlette / uvicorn 기반, CLI service-layer를 import 만 함(Constitution IV thin layer). | 본 spec은 web 모듈 추가 없음. ambiguous-mapping 큐 / 화이트리스트 결정의 web UI 통합은 scope OUT(Assumptions). 향후 별도 idea로 분리. | (검증 시나리오 없음 — 부재 검증 quickstart.md §7) |
| **B-12** | flake.nix devShell 시스템 의존성 | `chromaprint`, `ffmpeg`, `zlib`, `stdenv.cc.cc.lib` (spec 012). | 신규 추가: `cudnn`, `cuda-nvrtc` (faster-whisper GPU 런타임). 운영자 머신 NixOS 12.x 또는 unstable. | quickstart.md §0.1 + tests/contract/test_devshell_asr_import.py |
| **B-13** | huggingface-hub 모델 캐시 | 운영자 환경의 `HF_HOME` 또는 `~/.cache/huggingface/transformers/` — agenix 무관, 익명 다운로드. | faster-whisper 모델(large-v3 약 3 GB, int8 양자화 시 ~1.5 GB) 최초 1회 다운로드. 본 spec은 모델 캐시 위치를 영속 0 정책(Constitution V)에서 제외 — 운영자 환경 산출물로 간주. | quickstart.md §0.3 + tests/integration/test_asr_with_cached_model.py |

**Boundary 검증 의무**: 위 13개 항목 각각에 최소 1개 acceptance scenario 또는 통합 테스트가 매핑되어 있다. B-11(spec 008 web UI)은 의도적 부재 검증(out-of-scope assertion in `quickstart.md` §7).

**Failure 정책 (Principle II 일관)**: 미충족 boundary 값 발견 시(누락 alias / 토큰 / OAuth refresh / 디렉터리 / SQLite 버전 미만) 본 spec의 어떤 CLI 명령도 silently skip하지 않는다 — 모두 actionable 영문 메시지 후 거절(exit code 0이 아님).

---

## Requirements *(mandatory)*

### Functional Requirements

#### A. Takeout Ingestion 어댑터 (Phase 1)

- **FR-001**: System MUST accept a Takeout export root directory as input and produce both SQLite-resident channel/video metadata and JSON files (`channel_meta.json`, `videos_meta.json`) in the channel work directory, with SQLite as the authoritative source-of-truth and JSON files preserved for analysis-pipeline backward compatibility.
- **FR-002**: System MUST parse all 13 split metadata CSV files (`동영상.csv`, `동영상(1).csv`, …, `동영상(12).csv`), deduplicate by video_id, convert duration from milliseconds to seconds, and extract the channel_id from `채널.csv`.
- **FR-003**: System MUST map each Takeout mp4 file to a video_id using a multi-signal evidence score that combines (a) exact filename ↔ title match, (b) normalized filename ↔ title match, (c) ffprobe-measured duration ↔ metadata duration within ±1 second, (d) file size ↔ duration sanity ratio, and (e) file mtime ↔ metadata creation timestamp within ±1 day, with mtime weighted only as a supporting signal because compression/copy operations may damage it.
- **FR-004**: System MUST classify each mapping into one of three confidence buckets — `high` (score ≥ initial threshold), `medium` (score ≥ lower initial threshold), or `ambiguous` (score below the lower threshold OR multiple top-tier ties) — and persist the bucket on `processing_status.match_confidence` and `video_metadata.match_confidence`. Initial weight and threshold values MUST be tunable parameters subject to Phase 1 empirical adjustment.
- **FR-005**: System MUST write all ambiguous and unmapped mp4 files to an operator-editable CSV at `01_collect/_ambiguous_mappings.csv` with columns capturing the mp4 filename, candidate video_ids (comma-separated), candidate scores (comma-separated), the signal breakdown as JSON, and a reason. Re-running ingestion after operator edits MUST honor operator decisions and skip auto-mapping for resolved rows.
- **FR-006**: System MUST treat a `01_collect/_manual_mappings.csv` file, if present, as the first-class authoritative source of mp4 ↔ video_id mappings, bypassing the evidence score for any row listed there.
- **FR-007**: System MUST be fully idempotent for ingestion — re-running the same Takeout directory MUST cause no state changes, and ingesting a new Takeout part (`3-002`, `3-003`, …) MUST only accumulate new video_ids without altering existing rows.
- **FR-008**: System MUST explicitly ignore the following Takeout CSV / category sources, recording each ignore with reason `ignored_by_policy` in audit output: `동영상 녹화(*).csv`, `동영상 텍스트(*).csv`, `댓글.csv` (self-channel comments policy `project_no_comments`), `재생목록.csv`, `구독정보.csv`, `시청 기록/*.html`, `검색 기록.html`.
- **FR-009**: System MUST assemble all mp4 files into a per-channel unified work directory (default behavior: symbolic links into `data/<channel_alias>/videos/`; with `--copy` option: physical copy), and store mp4 file location as a relative path (`mp4_relative_path`) so that the data root can be moved without DB rewrites. `channel_metadata.takeout_root_hint` MUST hold the most recent ingestion's absolute root path purely as an operator memo, not as a runtime resolution input.

#### B. 오디오 추출 전처리 (Phase 1)

- **FR-010**: System MUST extract a single audio artifact (16 kHz, mono, PCM 16-bit WAV by default) from each mp4 so that audio fingerprint extraction and STT can share the same decoded input without double-decoding.
- **FR-011**: System MUST provide TWO operator-facing modes for audio extraction: a STANDALONE mode that accumulates WAV files in a cache directory for reuse across downstream commands, and an INTEGRATED per-video lifecycle mode (extract → fingerprint → STT → delete WAV) for full-channel runs where cache accumulation is unacceptable.
- **FR-012**: System MUST be idempotent on audio extraction — if a WAV for the target video_id already exists in the cache, extraction MUST be skipped unless `--force` is provided. A `--keep-audio` flag MUST be available in both modes to preserve WAV after downstream stages.

#### C. 음원 지문 추출 (Phase 1)

- **FR-013**: System MUST extract a chromaprint audio fingerprint from each video and persist it to the SQLite v3 `audio_fingerprint` table using the existing `services/audio_fingerprint.py` extraction primitive and `storage/content_db.py` persistence primitive.
- **FR-014**: System MUST expose a configurable `fingerprint_input_policy` parameter with values `original_mp4`, `wav_16k`, and `wav_22k`, and MUST NOT commit a default value until Phase 1 empirical comparison (same video, three policies, hamming distance measurement) is complete. The default selected after measurement MUST be persisted in the spec follow-up documentation.
- **FR-015**: System MUST persist fingerprint extraction so that re-running fingerprint over already-fingerprinted videos is idempotent (skip by default, `--force` to recompute).

#### D. STT 자막 생성 (Phase 2)

- **FR-016**: System MUST generate transcripts for videos lacking captions (primarily private/unlisted) using a local STT backend — local execution is a hard constraint, and external cloud STT APIs (OpenAI Whisper API / Google Cloud STT / Naver Clova / Azure) MUST NOT be introduced. The chosen local backend MUST support GPU acceleration, int8 quantization, and configurable model size / compute precision / device index via CLI options.
- **FR-017**: System MUST enforce hallucination defense defaults on every STT invocation: Voice Activity Detection on, condition-on-previous-text off, compression ratio threshold = 2.4, no-speech threshold = 0.6. Operators MAY opt out per option (e.g., `--no-vad-filter`) but defaults MUST be these values, not the upstream backend defaults.
- **FR-018**: System MUST detect and record ASR quality flags as JSON-serialized text in a new `quality_results.asr_quality_flags` column, with at least the following initial flags: `hallucination_repeat`, `vad_over_truncated`, `language_mismatch`, `short_segments_excess`, `silence_hallucination`, `compression_ratio_violations`. The flag set MUST be extensible without DB schema changes (single TEXT column, JSON payload validated by code-level schema).
- **FR-019**: System MUST output transcripts as `01_collect/transcripts/<video_id>.json` matching the spec 010/011 transcript JSON schema (per-segment `start`, `end`, `text` fields).
- **FR-020**: System MUST record exact provenance on `processing_status.caption_source` (enum: `transcript_api` / `captions_api` / `whisper`) AND on a new `processing_status.caption_source_detail` (TEXT, e.g., `asr:faster-whisper:large-v3:int8_float16`) so that the model / precision / device combination is reproducible.
- **FR-021**: System MUST expose four CLI presets — `poc-laptop` (RTX 3060 Laptop, 6 GB VRAM), `prod-a6000` (single A6000), `prod-a6000-pool` (dual A6000 worker pool), `cpu-fallback` — and operators MUST be able to override individual options (`--model`, `--compute-type`, `--device`, `--language`, `--beam-size`) on top of any preset.
- **FR-022**: System MUST implement the `prod-a6000-pool` preset as two independent Python worker processes, each pinned to one GPU (`cuda:0` / `cuda:1`), consuming a shared work queue backed by the SQLite `processing_status` table. Each worker MUST atomically claim a row by transitioning `status='collected' AND caption_source IS NULL` to `status='asr_in_progress'` within a transaction; on failure, MUST mark `status='asr_failed'` and proceed. With `--retry-failed`, workers MUST extend their claim predicate to `status IN ('collected', 'asr_failed') AND caption_source IS NULL`, transitioning directly from `asr_failed` to `asr_in_progress` in the same single atomic transaction (no intermediate reset stage). Concurrent retry attempts MUST remain race-free by relying solely on the SQLite transactional update — only one worker succeeds per row.
- **FR-023**: System MUST extend `VALID_PROCESSING_STATUSES` (Python frozenset) to include the two new values `asr_in_progress` and `asr_failed`. SQLite-level CHECK constraint reinforcement MAY be deferred to a follow-up migration because the existing `processing_status` table has no CHECK constraint and ALTER ADD CHECK requires table rebuild.

#### E. Text Normalizer (Phase 2)

- **FR-024**: System MUST normalize transcripts via a single common Text Normalizer regardless of source (ASR / API caption / manual), applying punctuation removal, whitespace collapse, NFC unicode normalization, lowercase folding for Latin text, and ASR meta-marker stripping (`[음악]`, `[박수]`, `(...)` etc.). Normalized output MUST be persisted to `01_collect/transcripts_normalized/<video_id>.json` so that comparison always reads the same input. **Single-source rule**: a given video_id MUST NOT carry both ASR and API caption transcripts simultaneously; conflict MUST be surfaced as an actionable operator message.
- **FR-025**: System MUST trigger normalization both automatically (default-on `--auto-normalize` at the end of `collect transcripts` and `collect process-audio`) and as a standalone idempotent command (`process normalize-transcripts`). Operators MUST be able to opt out of auto-normalization (`--no-auto-normalize`) or force re-normalization (`--force` on the standalone command).
- **FR-026**: System MUST record the source-type pair on each comparison result (`comparison_results.source_type_pair`, values like `asr-asr`, `api-api`, `asr-api`, `manual-asr`) so that downstream reports can flag heterogeneous-source comparisons explicitly.

#### F. 자막 출처 정책 (Phase 2)

- **FR-027**: System MUST follow the source-by-source separation policy: self-owned channels with private/unlisted videos use local ASR, and externally-owned channels' public videos use YouTube Data API caption download. The `--force-asr` option (re-processing public videos with ASR for consistency) MUST NOT be implemented in this spec.

#### G. 분석 — 8지표 + 매칭 모드 + 4계층 + 패턴 분류 (Phase 3)

- **FR-028**: System MUST complete the eight caption metrics — I-1 (SHA-256 hash), I-2 (cosine similarity), I-3 (word change rate), I-4 (new term count), I-5 (duration diff) from spec 007 baseline, plus I-6 (longest common segment), I-7 (segment run distribution), I-8 (alignment density) newly implemented in this spec. Column names MUST match `comparison_results` schema (e.g., `i6_longest_contiguous_seconds`, `i7_distribution_dispersion`, `i8_position_diversity`).
- **FR-029**: System MUST support two matching modes — `M-default` (spec 007: same professor + subject + week + session, different year only) and `M-nC2` (all pairs within one professor's video pool, e.g., 200 videos → 19,900 pairs). M-nC2 MUST first cull via Layer A length filter, then evaluate time-axis metrics only on surviving candidates.
- **FR-030**: System MUST apply four false-positive defense layers — Layer A (length threshold: contiguous matches shorter than N seconds are dropped), Layer B (professor baseline: n-grams appearing in ≥30% of a single professor's corpus are removed), Layer C (cross-professor IDF: terms common across the department-wide corpus are down-weighted), Layer D (whitelist: operator-curated `CONFIRMED_DUPLICATE` and `FALSE_POSITIVE` labels accumulate).
- **FR-031**: System MUST classify each above-threshold pair into one of the six reuse patterns — `whole-same-week`, `scattered-same-week`, `whole-different-week`, `scattered-different-week`, `re-recorded-same-content` (caption-similar / audio-different), `tail-update` (I-8 alignment ≈1.0 in front half, ≈0.0 in tail). The last two are this spec's new additions, contingent on audio fingerprint infrastructure being available.
- **FR-032**: System MUST compute pairwise audio fingerprint signals on every M-nC2 candidate pair — hamming distance, best offset, overlap seconds — and persist them in new `comparison_results` columns (`audio_fp_hamming`, `audio_fp_best_offset`, `audio_fp_overlap_seconds`).
- **FR-033**: System MUST keep analysis execution and report generation as two separate explicit commands. Report generation MUST NOT implicitly trigger analysis (re-running analysis is operator-explicit for reproducibility / debugging separation).
- **FR-034**: System MUST support resumable nC2 analysis via the existing `pair_checkpoint` table so that operator interruption mid-run does not lose progress.

#### H. 보고서 — 교수 단위 M-nC2 PDF/HTML (Phase 3)

- **FR-035**: System MUST generate a per-professor M-nC2 reuse report as both PDF and HTML (or operator-selectable via `--format pdf | html | both`) using an extension of the spec 006 report bundle infrastructure with a new template `professor_nC2_report.html`.
- **FR-036**: Report body MUST contain: cover page (channel, professor name, period, video count, pair count, generation timestamp), channel summary (subject distribution, year-over-year trend), per-metric distribution chart (one histogram per axis in `{i2_cosine, i6_longest_contiguous, i7_distribution_dispersion, i8_position_diversity, audio_fp_hamming}` — replaces "single aggregate suspicion grade chart" until weighted-sum is committed), top-K suspect pair list (K=50 default, operator-tunable; sort axis selected via `--sort-by <metric>`), pattern statistics (4 base patterns + 2 new patterns), and 4-layer false-positive defense application breakdown. A single aggregate "suspicion score" column MUST NOT be reported until the weighted-sum formula is committed in a spec follow-up.
- **FR-037**: Report tone MUST be reservation-form ("의심 근거", "검토 우선순위 상위", "주의 필요"); definitive verdict language ("재활용 확정", "위반") MUST NOT appear. Each suspect pair entry MUST present both quantitative evidence (which metric / which score) AND counter-evidence (which defense layer applied with what effect).
- **FR-038**: Report appendix MUST contain per-pair 1:1 detail pages for pairs exceeding operator-configurable per-metric thresholds (`--appendix-threshold-<metric> <value>`, one option per axis: `i2-cosine`, `i6-longest-contiguous`, `i7-distribution-dispersion`, `i8-position-diversity`, `audio-fp-hamming`). A pair MUST enter the appendix if ANY one specified threshold is exceeded (OR semantics). For the first 30 days of operation, all per-metric thresholds MUST default to "no threshold + per-metric distribution histogram included in the body" so that the operator can calibrate per-axis thresholds before they are fixed. Once the weighted-sum aggregate score formula is committed in a spec follow-up, this option set MUST be replaced by a single `--appendix-threshold <0..1>` against the aggregate score.
- **FR-039**: Each detail page MUST include the time-axis alignment view (matched-region color highlight on both captions), full time-axis profile chart, and audio-fingerprint alignment visualization.

#### I. 자막 KB Export (Phase 4)

- **FR-040**: System MUST export `transcripts/<video_id>.json` as clean plain text in the operator-selected format (`txt` / `md` / `jsonl`), stripping timestamps by default (`--keep-timestamps` to preserve), collapsing redundant segment newlines, optionally removing ASR filler patterns (`--clean-fillers`), with UTF-8 encoding and no BOM.
- **FR-041**: System MUST support both single-video export (`transcript export --video-id`) and bulk export (`transcript export-bulk --channel` or `--video-ids-file`).
- **FR-042**: Export MUST be source-agnostic: ASR-origin and API-caption-origin transcripts MUST produce identical export output structure (the originating source MAY be reported to the operator but MUST NOT alter the file format).

#### J. v4 DB 마이그레이션 (Cross-phase)

- **FR-043**: System MUST add two new SQLite tables — `channel_metadata` (channel_id PK, alias, title, country, privacy_status, source, takeout_root_hint, ingested_at) and `video_metadata` (video_id PK, channel_id FK, title, duration_seconds, language, category, privacy_status, created_at, published_at, source, match_confidence, mp4_relative_path, ingested_at) with the indexes specified in idea §8.
- **FR-044**: System MUST extend `processing_status` with `match_confidence` (TEXT) and `caption_source_detail` (TEXT) columns; extend `quality_results` with `asr_quality_flags` (TEXT JSON) column; extend `comparison_results` with `audio_fp_hamming`, `audio_fp_best_offset`, `audio_fp_overlap_seconds`, `source_type_pair` columns and new pattern enum values `re-recorded-same-content` and `tail-update`.
- **FR-045**: Migration MUST be reversible-safe — running ingestion on a pre-v4 database MUST automatically execute the v4 migration without operator intervention and MUST preserve all existing rows.

#### K. spec 012 (yt-dlp) 완전 삭제 (Phase 4)

- **FR-046**: System MUST remove all yt-dlp surface area in the final phase (idea Phase 4 / tasks.md Phase 5): `src/tube_scout/services/ytdlp_adapter.py`, `ytdlp_errors.py`, `srv3_parser.py` and their unit tests; the `--source ytdlp` branch and `_dispatch_ytdlp_transcripts` function in `cli/collect.py`; yt-dlp entries in `pyproject.toml` `dependencies`; yt-dlp packages in `flake.nix` devShell; the `specs/012-ytdlp-adapter/` directory contents (git history preserves the record); references in `CLAUDE.md` `Active Technologies` and recent-changes log. `pyacoustid` MUST be retained — `services/audio_fingerprint.py` (B-7) still depends on it.
- **FR-047**: System MUST keep P1 and P2 regression tests passing through and after the Phase 4 deletion. No spec 007/010/011/this-spec functionality MAY regress.

#### N. Audit Logging Surface (Cross-phase, Observability)

- **FR-057**: System MUST reuse the spec 012 `services/audit_writer.py` infrastructure (append-only CSV with per-stage frozen fieldnames) and extend it to cover all stages introduced in this spec. Each stage MUST write to a dedicated file `01_collect/{stage}_audit.csv` where `stage` is one of: `takeout_ingest`, `audio_extract`, `transcripts`, `fingerprint`, `normalize`, `analyze`, `report`, `kb_export`.
- **FR-058**: Each audit row MUST capture, at minimum, the columns: `timestamp` (ISO-8601 UTC), `video_id` (or `n/a` for channel-level events), `result` (machine-readable outcome — one of `success` / `skip` / `fail`), `reason` (machine-readable identifier — `ignored_by_policy`, `empty_transcript`, `language_mismatch`, `mapping_ambiguous`, `asr_failed`, `retry_claimed`, etc.), and stage-specific structured fields defined as a frozen schema per stage. This column set inherits the spec 012 `audit_writer.py` convention (B-5 boundary) — separate `event` column MUST NOT be introduced; the `reason` field carries both the machine identifier and operator-readable semantics. The full per-stage fieldname schema MUST be committed in the plan/data-model artifact.
- **FR-059**: Audit writers MUST be append-only — rewriting or deleting prior rows is forbidden. A failed write MUST surface as an actionable operator message rather than be silently swallowed.
- **FR-060**: Phase 4 yt-dlp deletion MUST relocate `services/audit_writer.py` outside the yt-dlp surface (it has been cross-stage utility since this spec ships) and MUST NOT remove it together with the yt-dlp adapter code. The post-Phase-4 location MUST be referenced from this spec's plan artifact.
- **FR-061**: Every long-running CLI invocation (`collect process-audio`, `collect transcripts`, `collect fingerprint --all-takeout`, `analyze content-reuse`, `report content-reuse`, `transcript export-bulk`) MUST emit progress signals in a form that auto-adapts to the runtime environment: when `sys.stdout.isatty()` is true, a rich.progress bar showing the current `video_id` or `pair_index`, elapsed time, ETA, and completed/total ratio MUST be displayed; when false (cron, nohup, ssh detach, journald capture), structured single-line log entries in the format `[stage] video_id=<id> N=<i>/total=<n> elapsed=<s>s ETA=<s>s` MUST be emitted at least once per processed video (or per N-pair batch for analysis), so that the operator can monitor progress through the captured log stream without TTY interaction.

#### M. 데이터 보존 정책 (Cross-phase, Compliance)

- **FR-053**: System MUST preserve Takeout-origin mp4 files indefinitely as the authoritative acquisition source (re-requesting a Takeout export from Google takes multiple days and is not a routine recovery path). Deletion of mp4 files MUST be operator-explicit (no automatic cleanup); the spec does not provide a `--prune-mp4` command in this release.
- **FR-054**: System MUST treat WAV extraction artifacts as non-persistent (retention policy) — in the integrated `collect process-audio` mode, the per-video WAV MUST be deleted immediately after the [fingerprint → STT] cycle completes. In the standalone `collect audio-extract` mode, WAV files accumulate in `--audio-cache-dir` until the operator clears the cache. The `--keep-audio` flag MUST override deletion in both modes for debugging. (FR-011 defines the operator-facing mode interface; this requirement covers retention only.)
- **FR-055**: System MUST preserve raw transcripts (`01_collect/transcripts/<video_id>.json`) and normalized transcripts (`01_collect/transcripts_normalized/<video_id>.json`) indefinitely as the re-execution input for analysis (`analyze content-reuse`) and KB export (`transcript export`). Deletion MUST be operator-explicit.
- **FR-056**: System MUST NOT introduce automatic retention timers, time-based purges, or `--retention-days` style policies in this spec. Future retention policy (if compliance requirements evolve) MUST be added via a separate idea/spec.

#### L. 영구 Scope OUT (negative requirements)

- **FR-048**: System MUST NOT introduce cloud-based STT or analysis APIs (OpenAI Whisper API, Google Cloud STT, Naver Clova, Azure Speech, etc.).
- **FR-049**: System MUST NOT analyze self-channel YouTube comments (policy `project_no_comments`).
- **FR-050**: System MUST NOT ingest Takeout `시청 기록`, `검색 기록`, `재생목록`, `구독정보`, `동영상 녹화`, `동영상 텍스트` categories. (For ingestion-time ignore behavior of these categories, see FR-008; self-channel `댓글.csv` is separately covered by FR-049.)
- **FR-051**: System MUST NOT analyze externally-owned (non-self) channels in this spec; cross-professor reuse detection (M-cross-prof) MUST NOT be implemented here.
- **FR-052**: System MUST NOT introduce OCR (slide visual reuse) or speaker diarization (single-video multi-professor split) — both permanently out per `project_scope_decisions_20260506`.

### Key Entities

- **TakeoutExport**: an operator-supplied root directory tree containing `Takeout/YouTube 및 YouTube Music/` subcategories. Source of truth for channel metadata, video metadata, and mp4 files. Identified by a root path; runtime resolution combines this with the channel work directory.
- **Channel Metadata**: per-channel record (channel_id, alias, title, country, privacy_status, source, takeout_root_hint, ingested_at). Dual-persisted in SQLite (authoritative) and `channel_meta.json` (analysis-pipeline compatibility).
- **Video Metadata**: per-video record (video_id, channel_id, title, duration_seconds, language, category, privacy_status, created_at, published_at, source, match_confidence, mp4_relative_path, ingested_at). Dual-persisted in SQLite and `videos_meta.json`.
- **mp4-to-video_id Mapping**: relationship between an on-disk mp4 file and a video_id, with confidence bucket (`high`/`medium`/`ambiguous`) and the underlying evidence-score signal breakdown. Operator-editable via `_ambiguous_mappings.csv` (resolution queue) and `_manual_mappings.csv` (authoritative override).
- **Audio Artifact**: per-video WAV file (16 kHz, mono, PCM) stored under a cache directory or `--audio-cache-dir`. Lifecycle is mode-dependent (accumulate / per-video delete / keep on flag).
- **Audio Fingerprint**: chromaprint output bound to a video_id, persisted as BLOB in `audio_fingerprint` (SQLite v3). Input source controlled by `fingerprint_input_policy`.
- **Transcript (Raw)**: per-video JSON at `01_collect/transcripts/<video_id>.json` with per-segment timing and text. Source is one of `transcript_api` / `captions_api` / `whisper` (with `caption_source_detail` capturing model/precision identity).
- **Transcript (Normalized)**: per-video JSON at `01_collect/transcripts_normalized/<video_id>.json` produced by the Text Normalizer. The input for all comparison metrics.
- **ASR Quality Flags**: JSON-encoded extensible flag set per video, persisted in `quality_results.asr_quality_flags`.
- **Comparison Result**: per-pair record across the eight caption metrics, the audio fingerprint signals, the reuse pattern label, the matching mode, and the source_type_pair. Persisted in `comparison_results`.
- **Match Span**: per-pair time-axis matched region detail used in time-axis metric calculation and report visualization.
- **Per-Professor M-nC2 Report**: HTML/PDF document covering one professor's full pair-wise comparison, with body (summary + top-K + statistics) and appendix (per-pair detail above threshold).
- **Knowledge Base Text Export**: per-video plain-text file (txt/md/jsonl) cleaned for external KB ingestion. Independent of analysis pipeline.

---

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: An operator can complete the four-step pipeline (`collect takeout` → `collect process-audio` → `analyze content-reuse` → `report content-reuse`) for one professor end-to-end without manual intervention beyond optionally editing the ambiguous-mapping queue.
- **SC-002**: For a 200-video professor (≈19,900 candidate pairs), the full M-nC2 analysis + report generation cycle completes within an operator-acceptable runtime budget. The exact wall-clock budget is set after Phase 1/2 measurements (Phase 1: 9-video end-to-end; Phase 2: full-channel ASR throughput on PoC and prod GPU) and committed in the spec follow-up before Phase 3 starts.
- **SC-003**: Auto-mapping (`high` + `medium` confidence) resolves ≥ a measurable percentage of Takeout mp4 files without operator intervention; the exact target percentage is set after Phase 1 measurement on the 9-video first-part Takeout export.
- **SC-004**: Whisper hallucination defense reduces the rate of silence-region filler-text generation ("구독과 좋아요…", "시청해주셔서 감사합니다") to near-zero on lecture audio. The remaining rate is captured in `quality_results.asr_quality_flags.hallucination_repeat` and `.silence_hallucination` for operator audit, and reviewed against the PoC video (5-1.임경민, 105 seconds) and at least one long-form video (>40 minutes) before Phase 2 ships.
- **SC-005**: Re-ingestion is fully idempotent — running `collect takeout` twice on the same Takeout part produces zero new rows in `channel_metadata`, `video_metadata`, `processing_status`, `audio_fingerprint`. Running a different part produces only the diff.
- **SC-006**: The per-professor report is operationally usable by a non-technical reviewer (educational affairs staff): with one PDF in hand, the reviewer can identify which video pairs to investigate first and read the supporting evidence + counter-evidence per pair, without referring back to raw CSVs or DB tables.
- **SC-007**: Report copy contains zero definitive-verdict language ("재활용 확정", "위반"); a sample of 20 random suspect-pair entries uses only reservation-form expressions ("의심 근거", "검토 우선순위 상위", "주의 필요").
- **SC-008**: Knowledge base export produces UTF-8 plain text that ingests cleanly into a generic external KB tool (verified by exporting the 9 PoC videos and importing into one operator-chosen KB pipeline before Phase 4 ships).
- **SC-009**: Phase 4 deletion leaves no `ytdlp`, `yt-dlp`, or `--source ytdlp` identifier in src · tests · docs · devShell, while spec 007 / 010 / 011 / this-spec test suites continue to pass.
- **SC-010**: Worker pool (`prod-a6000-pool`) processes a channel batch with both GPUs averaging > 70% busy time over a representative 30-minute window after Phase 2 ships on the prod GPU server.

---

## Assumptions

- **Acquisition 모델**: 운영자는 자교 채널의 Google Takeout export를 본인 계정에서 직접 신청 · 다운로드하여 로컬 머신(또는 외장 디스크)에 압축 해제한다. 외부 자동화로 Takeout을 받는 경로는 본 spec scope OUT이며, 이는 메모리 `project_takeout_pivot_20260512` 의 NON-NEGOTIABLE 결정.
- **분석·STT 실행 환경**: 분석과 STT는 모두 로컬 머신에서 수행한다. PoC는 RTX 3060 Laptop(6 GB VRAM), 운영은 별도 GPU 서버(A6000 ×2). 두 환경 모두 `flake.nix` devShell에 `chromaprint`, `ffmpeg`, GPU 드라이버가 셋업되어 있음.
- **OS · 환경**: 리눅스(NixOS / Gentoo) 기준. POSIX 심볼릭 링크가 지원되는 환경. Windows · macOS 호환성은 본 spec scope OUT — 필요 시 별도 idea로 분리.
- **spec 007 / 011 baseline**: 자막 5지표(I-1~I-5) 와 M-default 매칭은 spec 007이 master에 이미 들어가 있고 권위 코드로 본다. 시간축 3지표(I-6~I-8), M-nC2, 4계층 오탐 방어, 4패턴 분류는 spec 011 P1 미완 부분으로 본 spec에서 완성한다.
- **spec 012 (yt-dlp)**: master에 있으나 deprecated. 본 spec Phase 4에서 완전 삭제. Phase 1~3 동안은 두 흐름이 코드베이스에 공존하지만 운영자는 본 spec CLI만 사용한다(메모리 `feedback_account_isolation_policy` 잔존 정책).
- **chromaprint sample rate 일관성**: 검증 완료된 사항은 mp4 직접 입력(`fingerprint_input_policy='original_mp4'`)의 9개 영상 지문 정상 산출(2026-05-12). 16 kHz / 22 kHz WAV 입력 사이의 지문 동일성 여부는 Phase 1 실측 후 결정한다 — 본 spec은 측정 결과로 기본값을 확정한다는 약속만 둔다.
- **운영자 검토 흐름**: ambiguous 매핑 큐(`_ambiguous_mappings.csv`)와 화이트리스트 결정(Layer D)은 CLI · CSV 편집 기반이며 web admin UI 통합은 본 spec scope OUT(필요 시 spec 008 확장 idea로 분리).
- **이중 GPU 정책**: A6000 ×2 동시 활용은 비동기 워커 풀(cuda:0 / cuda:1 각 전담 프로세스)로 구현하며 모델 단위 sharding은 inter-GPU 통신 비용 때문에 채택하지 않는다.
- **`fingerprint_input_policy` 기본값 미확정**: Phase 1 실측 항목. 본 spec에서 기본값을 즉시 정하지 않고 측정 결과로 확정한다는 약속만 둔다. 이는 hidden technical risk가 아니라 명시적 측정 dependency.
- **Evidence Score 가중치 · 임계값**: 본 spec에 명시된 +40 / +30 / +25 / +5 / +5 가중치와 65 / 40 임계는 Phase 1 출발점이며 실측 자동화율을 토대로 spec 016 후속 업데이트에서 튜닝한다.
- **부록 임계 정책 + 단일 의심 점수**: Phase 3 출시 시점에는 single aggregate suspicion score를 정의하지 않는다. 보고서는 multi-axis(`--sort-by <metric>`) 정렬과 per-metric 분포 히스토그램으로 운영하며, 부록 컷은 axis별 임계(`--appendix-threshold-<metric>`, OR semantics)로 통제한다. 30일 누적 운영 데이터로 가중치 합산 공식을 spec follow-up에서 commit하면, 그 시점에 axis별 옵션 집합이 단일 `--appendix-threshold <0..1>` 로 전환된다.
- **외부 커뮤니케이션**: 본 spec의 Takeout 전환 사실은 YouTube · Google 등 외부 제출물에 노출하지 않는다(메모리 `feedback_external_comms_no_takeout`). YouTube Data API quota 회신은 별도 트랙으로 진행 — 본 spec과 독립.
- **자막 출처 단일성**: 한 video_id는 ASR 출처와 API caption 출처 중 하나만 갖는다. 동시 보유는 정책 위반이며 자동 우선순위 룰은 도입하지 않는다(운영자 결정 요구).
- **데이터 보존**: mp4(acquisition 원본)와 raw/normalized 자막 JSON은 영구 보존, WAV는 휘발성(통합 모드 즉시 삭제, 분리 모드 캐시 누적). 자동 retention 타이머·시간 기반 purge는 본 spec에 도입하지 않는다. 비공개 영상 데이터 컴플라이언스 요구가 진화하면 별도 idea로 분리.
- **첫 Takeout 입력**: 1차 export(`data/takeout-20260511T130817Z-3-001/`, 9 mp4 + 39 메타 CSV)가 디스크에 압축 해제되어 있다. 채널 전체 2,555개 영상 acquisition은 분할 part 누적 ingestion으로 점진 완성.
