# Feature Specification: unified_ingest 영구화 + 멱등 가드 (spec 017 PATCH)

**Feature Branch**: `018-ingest-persist-idempotent`
**Created**: 2026-05-16
**Status**: Draft
**Input**: User description: "idea/idea-spec018-unified-ingest-persistence-and-idempotency.md (commit 715e402 영속) — 본 시드 1 read 로 모든 결함 위치 (unified_ingest.py line 100/113/72) + 표준 fix 패턴 위치 (cli/collect.py:1931 + 2250) + 실측 증거 (T043 3 회차 14m36s) 흡수 — 추가 코드/로그 read 불필요"

## Clarifications

### Session 2026-05-16

- Q: `--force` 호출 시 `audio_fingerprint` row 갱신 정책은 무엇인가? → A: `INSERT OR REPLACE` (단일 statement upsert, video_id PK 유일성 자동 보장, spec 013 표준과 일관)
- Q: `--force` 호출과 `retry_pending.json` 매니페스트의 상호작용은? → A: `--force` 는 전체 영상 재처리 + retry_pending 자동 해소 (성공한 영상 entry 제거, 새 실패는 추가/유지)
- Q: 자막·지문 단계별 카운트의 단말 표시 형식은? → A: spec 017 의 기존 5-row Rich Table (적재 / 자막 생성 / 음원 지문 / 매니페스트 갱신 / 영상 정리) 를 보존하면서 열을 4 → 5 로 확장 (단계 / 처리 / skip / 실패 / 소요 시간). 자막 생성·음원 지문 행이 archive 크기와 무관하게 항상 존재하여 skip 정수가 단일 시선에 노출. 다른 행의 skip 열은 `-` 표시.
- Q: faster-whisper 모델 로딩 시점은 (멱등 hot path 최적화)? → A: 영상 사전 평가 후 자막 처리 대상 0 개면 모델 로딩 자체 skip (SC-018-1 의 ≤ 2 초 안정 만족 + GPU 메모리 점유 회피)
- Q: 자막·지문 정상성 점검 단계 존재 여부와 점검 fail 영상의 흐름은? → A: 점검은 `transcribe_audio` 가 반환하는 `asr_quality_flags` (6 종 flag — hallucination_repeat / language_mismatch / silence_hallucination / short_segments_excess / compression_ratio_violations / vad_over_truncated) 형태로 이미 산출됨. FR-018A 가 transcript json 의 `asr_quality_flags` 키로 함께 영구화. 점검 fail 영상 (flag 중 일부 true) 도 transcribe_audio 가 RuntimeError 를 raise 하지 않은 한 영구화 + retry_pending 미등재 + 다음 호출 시 멱등 skip (분리 명령 동작 인계 — FR-018H schema 동치성 보존). 운영자가 `--force` 또는 spec 011 후속 분석에서 flag 활용해 판단.

## 배경 *(요약)*

spec 017 의 `tube-scout collect ingest` 통합 명령은 Takeout archive 한 학과(=alias)에 대해 takeout 적재 → ASR 자막 추출 → chromaprint 지문 추출 → retry 매니페스트 생성 → optional source mp4 cleanup 까지를 한 사이클로 묶는다. 2026-05-16 T043 walkthrough 실측에서 같은 archive 에 대해 **세 번째 호출**도 14m36s (875.3s) 가 소요됨이 확인되었다. 즉 SC-004 (멱등 호출 시 추가 처리 0) 약속의 절반인 "DB 영상 행 추가 0" 만 통과하고, **자막·지문 재처리는 매 호출마다 반복**된다.

실측 표 (간호학과 archive 9.9 GB / 9 mp4 / 메타 2554, RTX 3060 + 표준 PC):

| 호출 회차 | wall clock | 자막 결과 | 지문 결과 | 매니페스트 | 비고 |
|---|---|---|---|---|---|
| 1 | ~64s | 0✓/9✗ | 9✓ | 9 추가 | libcublas.so.12 누락 |
| 2 (cuBLAS 정비) | 14m37s | 9✓/0✗ | 9✓ | 9 해소 | 정상 우선 재시도 |
| 3 (멱등 회귀) | **14m36s ❌** | 9✓/0✗ (재처리) | 9✓ (재처리) | 0 추가 / 0 해소 | **SC-004 위반** |

22 학과 운영 환산 시 재호출마다 14m36s × 22 = 약 5 시간 24 분 누적 낭비가 발생한다.

### 결함 3 건 (위치·증상)

- **결함 A — ASR 결과 휘발**: `src/tube_scout/services/unified_ingest.py:100` 의 `transcribe_audio(wav_path)` 가 반환값 (segments / language_detected / duration / asr_quality_flags / caption_source_detail) 을 받지 않고 폐기. 자막 텍스트가 디스크·DB 어디에도 저장되지 않는다. 실측: `data/<alias>/02_analyze/` 디렉토리 자체가 생성되지 않음.
- **결함 B — 지문 결과 휘발**: 같은 파일 line 113 의 `extract_chromaprint_fingerprint(wav_path)` 반환값 `(fp_b64_bytes, duration_seconds)` 도 폐기. `audio_fingerprint` 테이블에 row 가 추가되지 않는다.
- **결함 C — 멱등 가드 부재**: 같은 파일 line 72 의 영상 루프가 skip 조건 없이 모든 영상에 대해 무조건 WAV 추출 + ASR + 지문을 수행한다. 결함 A·B 로 인해 처리 결과가 어디에도 남지 않기 때문에, 가드를 둘 곳 자체가 부재한 구조적 부작용이다.

### 표준 fix 패턴 (코드베이스에 이미 존재)

spec 013 에서 동일 영구화·멱등 패턴이 분리 명령 두 곳에 이미 구현되어 있다 — 본 PATCH 는 통합 명령에 같은 패턴을 이식한다.

- 지문 영구화 + 멱등 가드: `src/tube_scout/cli/collect.py:1931-1956` (`collect_fingerprint_command`) — `SELECT 1 FROM audio_fingerprint WHERE video_id = ?` 가드 + `insert_audio_fingerprint` 영구화
- 자막 영구화: `src/tube_scout/cli/collect.py:2250-2295` (`process-audio` 의 통합 모드) — `tempfile.mkstemp` + `os.replace` atomic write, 위치 `data/<alias>/02_analyze/transcripts/<video_id>.json`

## User Scenarios & Testing *(mandatory)*

> **표기 약속**: 이하 acceptance scenario 와 Independent Test 의 "N" 은 처리 대상 mp4 매핑 수다. integration test fixture 에서는 N=3 (mini archive), 운영 baseline (간호학과 archive) 에서는 N=9. SC 본문의 정량 wall clock 은 N=9 / RTX 3060 기준 측정값이며, 다른 N 에서는 비례 환산한다.

### User Story 1 - 첫 호출에서 자막·지문이 영구 저장된다 (Priority: P1)

운영자가 한 학과 archive 에 대해 `tube-scout collect ingest --alias <학과>` 를 처음 호출하면, 통합 흐름이 끝난 시점에 자막 텍스트와 음향 지문이 **각각의 표준 위치에 영구화**되어 있어야 한다. spec 013 의 분리 명령 (`collect transcripts`, `collect fingerprint`) 산출물 위치와 schema 가 완전히 일치하여 후속 단계 (재사용 탐지 spec 011) 가 분리/통합 명령 어느 쪽으로 적재된 데이터든 동일하게 소비할 수 있어야 한다.

**Why this priority**: 영구화가 없으면 멱등(USR 2)·재처리(USR 3) 모두 의미를 잃는다. spec 017 의 "ingest = 한 사이클로 끝" 약속이 성립하기 위한 전제 조건이며, 분리/통합 명령 산출물 일관성이 spec 011 재사용 탐지의 입력 가정이다.

**Independent Test**: N mp4 가 든 fresh archive 에 대해 한 번 ingest 한 후 (1) `data/<alias>/02_analyze/transcripts/` 아래에 video_id 별 json N 개가 존재하고 각 파일이 video_id / source / language / duration / segments / asr_quality_flags / fetched_at 키를 갖는지, (2) 같은 alias 의 SQLite v4 DB 의 `audio_fingerprint` 테이블에 video_id N 개의 row 가 들어 있는지 검증한다. 어느 한쪽이라도 누락이면 실패다.

**Acceptance Scenarios**:

1. **Given** fresh archive (N mp4, 자막·지문 산출물 없음), **When** `tube-scout collect ingest --alias <학과>` 호출, **Then** 호출 종료 시점에 transcripts/ 디렉토리에 video_id 별 json N 개가 atomic write 되어 있다 (부분 작성 흔적 `*.tmp` 0 개).
2. **Given** 같은 fresh archive, **When** 동일 호출, **Then** 호출 종료 시점에 `audio_fingerprint` 테이블에 video_id N 개의 row 가 fingerprint(blob) + duration(real) + fetched_at(ts) 와 함께 영구화되어 있다.
3. **Given** spec 013 분리 명령 (`collect transcripts` + `collect fingerprint`) 으로 적재한 archive, **When** 같은 학과를 통합 명령으로 호출, **Then** 분리/통합 산출물의 json schema (키 집합) 와 DB row schema 가 동일하여 후속 재사용 탐지 명령이 추가 분기 없이 두 산출물을 동시에 읽는다.

---

### User Story 2 - 두 번째 호출은 즉시 끝난다 (Priority: P1)

같은 archive 에 대해 ingest 를 두 번째 이상 호출하면, 이미 처리된 영상은 **WAV 추출 단계부터 skip** 되어 사이클이 거의 즉시 종료되어야 한다. Rich Table 의 "성공/실패/skip" 표시로 운영자가 멱등이 동작 중임을 시각적으로 확인할 수 있어야 한다.

**Why this priority**: SC-004 의 반쪽이자 본 PATCH 의 주된 동기다. 22 학과 운영 환산 시 약 5 시간 24 분의 GPU 시간 절감이 직접 측정 가능한 효과다. 또한 운영자가 부분 실패 후 재시도 (retry_pending.json 해소) 를 자유롭게 호출할 수 있는 흐름 전제다.

**Independent Test**: USR 1 의 산출물 (transcripts json N + audio_fingerprint row N) 이 존재하는 archive 에 대해 `tube-scout collect ingest --alias <학과>` 를 호출한다. (1) **자막·지문 단계** wall clock ≤ 2 초 (N=9 / RTX 3060 기준, 다른 N 에서는 비례 환산) / 전체 명령 wall clock ≤ 30 초 (적재 포함), (2) 5-row Rich Table 의 자막 생성 행과 음원 지문 행에서 "skip = N / 처리 = 0 / 실패 = 0", (3) GPU 사용량 0 (faster-whisper 로드 자체 skip 가능 시), (4) 매니페스트 retry_pending.json 추가/해소 0 을 검증한다.

**Acceptance Scenarios**:

1. **Given** transcripts/ 에 video_id 별 json N 개 + DB 의 `audio_fingerprint` row N 개가 존재, **When** `collect ingest --alias <학과>` 호출, **Then** 자막·지문 단계 wall clock ≤ 2 초 (N=9 기준) / 전체 명령 wall clock ≤ 30 초 이내 종료한다.
2. **Given** 같은 상태, **When** 같은 호출, **Then** 단말의 5-row Rich Table (적재 / 자막 생성 / 음원 지문 / 매니페스트 갱신 / 영상 정리) 의 자막 생성 행과 음원 지문 행에서 skip 열이 N, 처리 열이 0, 실패 열이 0 으로 표시되어 운영자가 멱등 동작을 인지할 수 있다.
3. **Given** 같은 상태, **When** 같은 호출, **Then** 감사 CSV (`audit_writer.py` 의 `ingest_orchestrator` stage) 에 자막·지문 각각의 N 행 skip 이유 (`already_transcribed`, `already_fingerprinted`) 가 기록된다.
4. **Given** 같은 상태, **When** 같은 호출, **Then** WAV 임시 파일이 단 한 개도 생성되지 않거나 (자막·지문 둘 다 skip 인 영상에 대해 디코딩 자체를 건너뜀), 생성되더라도 즉시 정리된다.
5. **Given** 같은 상태, **When** 같은 호출, **Then** faster-whisper 모델이 로드되지 않는다 (GPU 메모리에 모델 가중치 적재 0, CTranslate2 init 시간 0).

---

### User Story 3 - 강제 재처리 옵션이 있다 (Priority: P2)

운영자가 자막 모델을 교체하거나 chromaprint 옵션을 바꾼 후 같은 archive 에 대해 재처리가 필요할 수 있다. 이때 멱등 가드를 우회하여 모든 영상을 강제로 재처리하는 명시적 옵션이 있어야 한다.

**Why this priority**: 운영 유연성을 위한 필수 escape hatch 다. spec 013 의 `collect fingerprint --force` 와 시그니처가 일관되어야 한다. 다만 일상 사용 빈도가 낮아 USR 1/2 보다 우선순위가 낮다.

**Independent Test**: USR 1 상태의 archive 에 대해 `tube-scout collect ingest --alias <학과> --force` 를 호출하고 (1) wall clock 이 fresh 처리에 준하는 시간 (RTX 3060 기준 9 mp4 / 약 14m36s) 으로 돌아오고, (2) transcripts json mtime 이 갱신되고, (3) `audio_fingerprint` row 가 동일 video_id 에 대해 `INSERT OR REPLACE` 로 덮어써져 row 수가 정확히 1 개로 유지되며 `fetched_at` 이 갱신되는지 검증한다.

**Acceptance Scenarios**:

1. **Given** transcripts/ 와 `audio_fingerprint` 가 모두 채워진 상태, **When** `collect ingest --alias <학과> --force` 호출, **Then** 모든 영상에 대해 ASR + 지문 처리가 다시 실행된다 (skip 0).
2. **Given** 같은 상태, **When** `--force` 호출 종료, **Then** transcripts json N 개의 mtime 이 호출 시각 이후로 갱신되고 `audio_fingerprint` row N 개의 `fetched_at` 도 갱신된다 (스키마 변경 없이 동일 video_id 의 row 가 최신값으로 유지).
3. **Given** 운영자 매뉴얼·`--help` 출력, **When** 옵션 설명을 읽음, **Then** `--force` 가 "멱등 가드 우회, 자막·지문 강제 재처리" 로 명확히 설명되어 있다.

---

### Edge Cases

- **부분 영구화 상태 (자막 json 있고 지문 row 없음)**: 자막은 skip, 지문은 처리한다 (또는 그 반대). 두 가드는 독립적으로 평가된다.
- **자막 json 이 `*.tmp` 로 남아 있는 경우**: atomic write 실패 잔재로 간주, 자막 가드는 false (재처리 대상). `*.tmp` 는 다음 atomic write 가 덮어쓰거나 정리한다.
- **archive 내 mp4 가 0 개**: 통합 흐름은 takeout 적재까지만 수행 (현재 동작 유지), 자막·지문 단계는 즉시 "처리 0 / skip 0" 으로 종료.
- **transcripts/ 디렉토리가 존재하지 않음**: `_run_transcript_and_fingerprint` 진입 시점에 mkdir -p 로 생성한다 (멱등 mkdir).
- **DB schema 호환 검사 실패**: spec 013 의 `audio_fingerprint` 테이블이 존재하지 않으면 (스키마 미초기화) 진입 즉시 명확한 오류로 실패하고 운영자가 마이그레이션을 수행하도록 안내한다. 자동 생성하지 않는다 (boundary fail-fast).
- **`--force` 호출 중 일부 영상 실패**: 새로 실패한 영상만 retry_pending.json 에 등재 (또는 기존 entry 유지), 새로 성공한 영상은 retry_pending.json 에서 자동 해소된다. 성공한 영상의 영구화는 호출 종료 시점에 이미 디스크/DB 에 반영되어 있다 (atomic write + sqlite commit 단위).
- **점검 결과 fail 영상 (asr_quality_flags 중 일부 true)**: `transcribe_audio` 가 RuntimeError 를 raise 하지 않은 한 transcript json 은 정상 영구화되고 retry_pending.json 에는 등재되지 않는다 (분리 명령 `collect transcripts` 동작 인계, FR-018H schema 동치성 보존). 멱등 가드는 json 존재 여부만 보므로 다음 호출에서 skip 되며, 운영자가 `--force` 명시 또는 spec 011 후속 분석에서 `asr_quality_flags` 를 확인하여 재처리 여부를 판단한다. 본 PATCH 가 자동 재시도 정책을 새로 도입하지는 않는다.
- **두 호출이 동시에 진행 (concurrent ingest)**: 같은 alias 에 대해 두 프로세스가 동시에 도는 시나리오는 본 PATCH 의 범위 밖이다 — 운영 규칙으로 직렬 호출만 허용한다고 가정한다 (자세한 lock 도입은 별 spec).
- **transcripts/ 가 다른 사용자 권한으로 작성됨**: atomic write 실패 시 명시적 PermissionError 로 fail-fast.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-018A**: 시스템은 통합 명령의 자막 처리 단계가 종료될 때, 각 영상의 ASR 산출물 (video_id / source / language / duration / segments / **asr_quality_flags** / fetched_at) 을 `data/<alias>/02_analyze/transcripts/<video_id>.json` 에 **atomic 하게 영구화**해야 한다. 부분 작성 흔적(.tmp) 이 종료 시점에 남지 않아야 한다. 여기서 `asr_quality_flags` 는 `transcribe_audio` 가 산출하는 6 종 ASR 정상성 평가 결과 (hallucination_repeat, language_mismatch, silence_hallucination, short_segments_excess, compression_ratio_violations, vad_over_truncated) 를 그대로 직렬화한 값으로, 운영자 검토와 spec 011 후속 분석이 자막 신뢰도를 평가하는 입력이 된다. (해결: 결함 A)
- **FR-018B**: 시스템은 통합 명령의 지문 처리 단계가 종료될 때, 각 영상의 chromaprint 산출물 (fingerprint blob, duration_seconds, fetched_at) 을 `audio_fingerprint` 테이블에 **`INSERT OR REPLACE` 단일 statement 로 영구화**해야 한다. video_id PK 유일성이 SQL 수준에서 자동 보장되며, schema 는 spec 013 의 기존 schema 를 그대로 보존한다. `--force` 재처리 시에도 동일 statement 가 기존 row 를 덮어쓴다. (해결: 결함 B)
- **FR-018C**: 시스템은 영상별 처리 진입 전에 **두 개의 독립 멱등 가드**를 평가해야 한다 — 자막: 표준 위치의 json 존재 여부, 지문: DB row 존재 여부. 가드가 참인 단계는 skip 하고 감사 로그에 사유 (`already_transcribed` / `already_fingerprinted`) 를 기록한다. (해결: 결함 C)
- **FR-018D**: 시스템은 `collect ingest` 에 **`--force` 옵션** 을 제공하여, FR-018C 의 두 멱등 가드를 모두 우회하고 강제 재처리를 수행해야 한다. 옵션은 spec 013 의 `collect fingerprint --force` 와 시그니처·의미가 일관되어야 한다. `--force` 호출은 archive 내 **전체 영상** (이미 성공한 영상 + retry_pending.json 에 등재된 실패 영상) 을 모두 재처리 대상으로 삼으며, 호출 종료 시점에 새로 성공한 영상은 retry_pending.json 에서 자동 해소되고 새로 실패한 영상은 추가 또는 유지된다.
- **FR-018E**: 시스템은 자막·지문 두 단계가 모두 skip 인 영상에 대해 **WAV 추출(디코딩) 자체를 skip** 해야 한다. spec 017 SC-005 의 "영상당 디코딩 1 회" 약속이 멱등 호출 시 "0 회" 로 강화된다. 추가로 archive 내 자막 처리 대상이 0 개로 사전 평가되는 경우 **faster-whisper 모델 로딩 자체도 skip** 되어야 한다 (≈ 3–5 초의 모델 init 비용 회피, SC-018-1 의 ≤ 2 초 목표 안정 만족).
- **FR-018F**: 시스템은 자막·지문 단계의 처리/skip/실패 카운트를 **단말의 Rich Table** 과 감사 CSV (`audit_writer` 의 `ingest_orchestrator` stage) 양쪽에 기록해야 한다. Rich Table 은 spec 017 의 기존 5-row 구조 (적재 / 자막 생성 / 음원 지문 / 매니페스트 갱신 / 영상 정리) 를 **보존**하면서 열을 4 → 5 로 확장한다 — 신규 컬럼 셋은 (단계 / 처리 / skip / 실패 / 소요 시간). 자막 생성 행과 음원 지문 행은 archive 영상 수와 무관하게 항상 존재하여 skip 카운트가 단일 시선에서 읽힌다. 다른 행 (적재 / 매니페스트 / 영상 정리) 의 skip 열은 의미가 없으므로 `-` 또는 빈 값으로 표시한다.
- **FR-018G**: 시스템의 spec 017 quickstart §5 KNOWN LIMITATION 항목 (멱등 부분 실패) 은 본 PATCH 완료와 함께 **제거 또는 RESOLVED 표시** 되어야 한다. 새 운영자가 quickstart 만 읽고도 멱등이 약속대로 동작함을 인지할 수 있어야 한다.
- **FR-018H**: 시스템은 spec 011 (재사용 탐지) 의 입력 소비 시점에 분리 명령 (`collect transcripts` / `collect fingerprint`) 과 통합 명령 (`collect ingest`) 의 산출물을 **구분 없이 동일하게 소비**할 수 있어야 한다. 즉 두 경로의 transcripts json 의 schema (top-level 키 + asr_quality_flags 키 + segment 객체 키) 와 `audio_fingerprint` row 의 컬럼 셋이 schema-for-schema 동치여야 한다. 단, segment 의 값과 fetched_at 은 호출마다 달라지므로 동치 대상에서 제외된다.

### Key Entities *(include if feature involves data)*

- **Transcript Artifact (자막 산출물)**: 영상 한 개의 ASR 결과. 표준 위치 `data/<alias>/02_analyze/transcripts/<video_id>.json`. 키: video_id, source (`asr_local_faster_whisper` 등), language, duration, segments (list), asr_quality_flags (object), fetched_at (ISO 8601). atomic write 단위 = 단일 json 파일.
- **Audio Fingerprint Row (지문 row)**: 영상 한 개의 chromaprint 지문. DB 위치: SQLite v4 의 `audio_fingerprint` 테이블 (spec 013 정의 보존). 키: video_id (PK or unique), fingerprint (blob), duration_seconds (real), fetched_at (ts).
- **Idempotency Guard (멱등 가드)**: 영상별·단계별 (자막/지문) 의 skip 판단 결과. 입력: video_id + 자막 json 존재 여부 + audio_fingerprint row 존재 여부 + `--force` 여부. 출력: `process` / `skip(reason)` 두 가지.
- **Ingest Audit Entry (감사 행)**: 단일 영상-단계 처리 결과 한 행. 키: alias, video_id, stage (`transcript` / `fingerprint`), action (`process` / `skip` / `fail`), reason, ts, latency_ms.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-018-1 (SC-004 회복 / 핵심 지표)**: 같은 archive 에 대한 두 번째 호출에서 **자막·지문 단계** (`_run_transcript_and_fingerprint`) 의 wall clock 이 **≤ 2 초** 이내 종료하고 (N=9 / RTX 3060 기준, 다른 N 에서는 비례 환산), 자막·지문 단계가 "skip N / 처리 0 / 실패 0" 으로 보고된다. 매니페스트는 추가 0 / 해소 0. Takeout 적재 단계 (~8s) 를 포함한 전체 명령 wall clock 은 ≤ 30 초. (자막·지문 단계 현재 측정값 14m36s → 목표 ≤ 2 초.)
- **SC-018-2 (영구화 완료)**: 첫 호출 종료 시점에 `data/<alias>/02_analyze/transcripts/` 에 video_id 별 json N 개 (N = archive 의 mp4 매핑 수) 가 atomic write 되어 있고 (부분 작성 `*.tmp` 0 개), `audio_fingerprint` 테이블에 video_id N 개의 row 가 fingerprint blob + duration + fetched_at 와 함께 영구화되어 있다.
- **SC-018-3 (강제 재처리)**: `--force` 호출 시 멱등 가드를 우회하여 자막·지문 모두 재처리되며, wall clock 이 fresh 처리에 준하는 범위 (간호학과 archive 기준 14m ± 2m) 로 돌아오고, transcripts json mtime 과 `audio_fingerprint` row 의 `fetched_at` 이 갱신된다. `audio_fingerprint` 의 동일 video_id 에 대한 row 수는 재처리 후에도 정확히 1 개 (`INSERT OR REPLACE` 의 PK 단일성 보장).
- **SC-018-4 (22 학과 운영 환산 GPU 절감)**: 22 학과 모두에 대한 멱등 재호출 (두 번째 호출) 의 **자막·지문 단계** 누적 wall clock 이 ≤ 44 초 (= 22 × 2 초) 로, 현재 약 5 시간 24 분 대비 99% 이상 절감된다. Takeout 적재 포함 전체 명령 기준으로는 ≤ 22 × 30 초 = 660 초. 운영 비용 회복이 단일 학과 측정으로부터 직접 환산 가능하다.
- **SC-018-5 (산출물 schema 동치)**: spec 013 분리 명령으로 적재한 archive 한 개와 본 PATCH 의 통합 명령으로 적재한 archive 한 개의 산출물이 **schema-for-schema 동치** 다 — 구체적으로 transcripts json 의 top-level 7 키 + `asr_quality_flags` 의 6 종 flag 키 + segment 객체 키, 그리고 `audio_fingerprint` row 의 컬럼 집합이 모두 일치한다. segment 의 값 (timestamp, text 등) 과 `fetched_at` 은 호출마다 자연스럽게 달라지므로 동치 대상에서 제외된다. spec 011 의 입력 reader 가 어느 경로의 산출물이든 분기 없이 소비할 수 있다.
- **SC-018-6 (단말 가시성)**: spec 017 의 5-row Rich Table 가 5-col 구조 (단계 / 처리 / skip / 실패 / 소요 시간) 로 확장되어, 자막 생성 행과 음원 지문 행이 archive 영상 수와 무관하게 항상 존재한다. 운영자가 두 행의 skip 열을 보고 멱등 동작 여부를 5 초 이내 인지 가능함은 quickstart 의 실측 walkthrough (T043) 에서 운영자 stopwatch 측정으로 검증한다 — 또는 시각 구조 verification (행 5 × 열 5, 자막/지문 행 항상 존재, skip 열 색상 강조) 만으로도 충족된 것으로 간주한다.
- **SC-018-7 (회귀 안정성)**: spec 017 의 SC-001 (ffprobe 메모이즈로 적재 ≤ 60s), SC-005 (영상당 디코딩 1 회), SC-002~SC-003 (retry_pending 흐름), C-1 (임시 WAV 즉시 정리) 모든 기존 성공 기준이 본 PATCH 후에도 유지된다 — 회귀 테스트 모두 GREEN.

## Assumptions

- spec 017 의 `collect ingest` CLI 진입점·옵션 구조는 본 PATCH 의 범위 밖이며 그대로 보존된다. `--force` 추가만이 유일한 신규 옵션이다.
- spec 013 의 SQLite v4 schema (`audio_fingerprint`, `processing_status`, `quality_results`, `comparison_results`) 는 변경하지 않는다. 본 PATCH 는 schema migration 을 수반하지 않는다.
- 자막 atomic write 위치 `data/<alias>/02_analyze/transcripts/<video_id>.json` 는 spec 013 의 `collect transcripts` 산출 경로와 동일하며 본 PATCH 후에도 유지된다.
- ASR 모델·chromaprint 파라미터는 본 PATCH 의 범위 밖이다 — 동일 영상에 대해 두 번 처리하면 (`--force`) 산출물이 동일하다는 보장은 별 spec 의 책임이다.
- 운영 모드는 같은 alias 에 대한 ingest 직렬 호출 (concurrent ingest 없음) 만을 가정한다. 다중 프로세스 잠금은 본 PATCH 의 범위 밖이다.
- 실측 baseline (T043 3 회차, 9 mp4, RTX 3060) 이 22 학과 운영의 representative sample 로 기능한다. 22 학과 환산은 선형 비례를 가정한다.
- 22 학과 운영의 GPU 비용 절감 (SC-018-4) 측정은 한 학과 측정 + 환산으로 충분하며 22 학과 모두에 대한 실측을 본 PATCH 의 acceptance 조건으로 요구하지 않는다.
- pyproject 버전은 본 PATCH 진행 중 `0.6.0.dev0` 를 유지하고, 완료 시점에 0.6.0 final 또는 0.6.1 결정은 사용자 판단에 위임한다.
- ASR 결과 정상성 평가 (asr_quality_flags 6 종) 의 산출 로직은 `transcribe_audio` 가 이미 보유 (`src/tube_scout/services/asr.py:detect_quality_flags`) 하므로 본 PATCH 는 신규 점검 로직을 도입하지 않는다. `quality_results` 테이블 row 영구화는 분리 명령도 현재 수행하지 않으므로 본 PATCH 의 범위 밖이며, 필요 시 별 spec 으로 보강한다. 점검 fail 영상의 자동 재시도 정책 도입도 본 PATCH 의 범위 밖이다 (분리 명령 동작 그대로 인계).
- 임시 음원 (WAV) 의 비영구화 정책은 spec 017 FR-007 / Edge case "임시 음원의 비영구화" 와 `audio_extract.WavLifecycle` 구현이 이미 보장하므로 본 PATCH 는 별도 FR 을 두지 않는다. 자막·지문 양쪽 처리가 끝난 시점에 (점검 결과와 무관하게) context manager 가 WAV 를 즉시 정리한다.
- 영상 본체 (mp4) 의 보존·삭제 규칙은 spec 017 의 `--delete-source` 두 단계 interactive prompt 가 통합 명령에 살아있는 상태로 인계되며 본 PATCH 는 그 동작을 변경하지 않는다.
