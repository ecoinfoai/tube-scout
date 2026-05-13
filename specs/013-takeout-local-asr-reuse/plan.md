# Implementation Plan: Takeout 기반 로컬 ASR + 강의 영상 재사용 판정 + 자막 KB Export

**Branch**: `013-takeout-local-asr-reuse` | **Date**: 2026-05-13 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/013-takeout-local-asr-reuse/spec.md`
**Constitution**: v1.1.0 (`.specify/memory/constitution.md`)
**Target Release**: v0.5.0 (Phase 1~4 단위 머지, 최종 Phase 4에서 v0.5.0 release)
**Selected Clarifications** (`./spec.md` §Clarifications):
- C-1 데이터 보존: mp4 영구, WAV 비영구(통합 모드 즉시 삭제), 자막 JSON 영구
- C-2 Audit logging: spec 012 `audit_writer` 인프라 계승·확장, 단계별 CSV 분리
- C-3 단일 의심 점수: Multi-axis 한시 운영 + 30일 후 가중치 합산 공식 후속 commit
- C-4 Progress reporting: `sys.stdout.isatty()` 자동 감지 (TTY=rich.progress, 비-TTY=structured log)
- C-5 `--retry-failed`: `asr_failed` → `asr_in_progress` 직접 atomic 전이, claim predicate 확장

---

## Summary

자교 채널의 Google Takeout export를 입력으로 받아 (1) 채널 메타·영상 메타·mp4↔video_id 매핑을 SQLite v4 / JSON 이중 적재하고, (2) mp4에서 16 kHz mono WAV를 한 번만 추출해 음원 지문(chromaprint, spec 012 master 재사용)과 STT(local faster-whisper, 신규)가 공유하는 입력으로 사용하며, (3) ASR 출력 + YouTube Data API caption(공개 채널)을 공통 Text Normalizer로 정규화한 뒤 spec 011 미완 분석 파이프라인(I-6~I-8 시간축 지표 + M-nC2 매칭 모드 + 4계층 오탐 방어 + 4패턴 분류 + 신설 2패턴)을 완성한다. 한 교수 단위 M-nC2 비교 결과는 spec 006 report bundle 인프라를 확장한 PDF/HTML 보고서로 출력되며, multi-axis 정렬 · per-metric 임계 컷 · 분포 히스토그램으로 운영 첫 30일을 운영자가 직접 calibrate한 뒤 가중치 합산 공식을 spec follow-up에서 commit한다. KB 입력 export는 자막 JSON을 깨끗한 평문(txt/md/jsonl)으로 변환하는 독립 CLI로 분리되며, Phase 4에서 spec 012 yt-dlp surface 전체가 코드베이스에서 완전 삭제된다(공기관 운영 적합성 사유).

기술 접근: 로컬 STT는 faster-whisper(CTranslate2 백엔드, int8 양자화) 기본, hallucination 방어 4종을 코드 강제. 워커 풀(`prod-a6000-pool`)은 SQLite `processing_status` 테이블을 큐로 사용하는 두 Python 프로세스(cuda:0 / cuda:1 전담), atomic claim 트랜잭션 패턴(C-5). audit logging은 spec 012 `services/audit_writer.py`를 cross-stage 일반화 모듈로 재배치(`services/audit_writer.py`는 Phase 4에도 유지). progress는 환경 자동 감지(C-4). 보고서 단일 의심 점수는 multi-axis로 30일 한시 운영(C-3). v4 마이그레이션은 `migrate_to_v4()` 함수 한 번 호출로 멱등 적용.

---

## Technical Context

**Language/Version**: Python 3.11 (pinned via `flake.nix` devShell + `pyproject.toml`)

**Primary Dependencies**:
- 신규 (PyPI): `faster-whisper>=1.0.0` (CTranslate2 backend, int8 양자화 지원). 단일 패키지 — `transformers`/`torch` 직접 의존 없음(faster-whisper가 자체적으로 ctranslate2 + tokenizers만 사용).
- 신규 (PyPI, faster-whisper transitive): `ctranslate2`, `tokenizers`, `onnxruntime`(silero-vad용), `huggingface-hub`(모델 다운로드)
- 신규 (Nix system): `cudnn`, `cuda-nvrtc` (faster-whisper GPU 런타임). 기존 chromaprint + ffmpeg + zlib + stdenv.cc.cc.lib는 spec 012가 이미 추가.
- 기존 재사용: `typer`, `rich`, `pydantic v2`, `polars`, `jinja2`, `weasyprint`(PDF, optional `pdf` extra), `httpx`, `google-api-python-client`(spec 005/009 OAuth 경유 captions_api).
- 기존 코드 재사용: `services/audio_fingerprint.py` (spec 012 master), `services/nc2_matcher.py` (spec 011, 부분 구현), `services/pair_checkpoint.py` (spec 011), `services/layer_defense.py` / `phrase_whitelist.py` / `baseline_corpus.py` (spec 011), `services/pattern_classifier.py` (spec 011), `services/time_axis_indicators.py` (spec 011 부분), `storage/content_db.py` v3 → v4 migration 함수 추가, `services/audit_writer.py` (spec 012, cross-stage 일반화).

**Storage**:
- 메타: `channel_metadata`, `video_metadata` 신규 테이블 (SQLite v4) + `channel_meta.json`, `videos_meta.json` (분석 파이프 호환, 이중 적재)
- 매핑 큐: `01_collect/_ambiguous_mappings.csv`, `01_collect/_manual_mappings.csv` (운영자 편집형)
- 작업 디렉터리: `data/<channel_alias>/videos/` (mp4 symlink 또는 `--copy` 시 복사본)
- 자막 raw: `01_collect/transcripts/<video_id>.json` (spec 010/011 schema)
- 자막 정규화: `01_collect/transcripts_normalized/<video_id>.json` (Text Normalizer 출력, 신규)
- 음원 임시 wav: `<audio_cache_dir>/<video_id>.wav` (기본 임시 경로, `--audio-cache-dir`로 override)
- 음원 지문: SQLite v3 `audio_fingerprint` 테이블 (spec 012 그대로)
- 비교 결과: SQLite v4 `comparison_results` (audio_fp_* + source_type_pair + 신설 패턴 enum)
- 시간축 정렬: SQLite v4 `match_spans` (spec 011 미완 부분 완성)
- 품질 지표: SQLite v4 `quality_results.asr_quality_flags` (JSON TEXT, 신규 컬럼)
- Audit CSV: `01_collect/{stage}_audit.csv` × 8단계 (spec 012 audit_writer 인프라 계승)
- 보고서: `projects/{job-id}/03_report/<professor>_nC2_report.{html,pdf}` (spec 006 bundle 인프라)
- KB export: 운영자 지정 출력 경로 (기본 `--output ./kb_export/<video_id>.{txt,md,jsonl}`)

**Testing**: `pytest`, `pytest-asyncio` (기존), `pytest-cov` (기존). Local STT 통합 테스트는 PoC 영상(`5-1.임경민`, 105초) 사용. `@pytest.mark.slow` 마커로 분리 — CI는 1분 미만 unit + contract만, slow 마커는 nightly.

**Target Platform**: NixOS / Gentoo Linux (POSIX 심볼릭 링크 가정). Windows · macOS 호환성 scope OUT. Python 3.11 단일.

**Project Type**: CLI tool (Typer) — Constitution IV CLI-First. 신규 웹 surface 0건. spec 008 admin web과는 단방향 read 가능성만 있고 본 spec은 web 모듈 추가 없음.

**Performance Goals** (대부분 Phase 1·2 측정 후 commit — Clarification deferred):
- Takeout ingestion (9 mp4 + 39 메타 CSV, 1차 part 기준): 매핑 자동화율(`high` + `medium`) ≥ 측정 후 commit, wall-clock ≤ 측정 후 commit.
- 오디오 추출 + 지문 (9 영상): 영상당 wall-clock ≤ 측정 후 commit (spec 012 master에서 9.9 GB 9개 영상 4.9초 최대 측정 — 출발점).
- STT (faster-whisper, PoC GPU = RTX 3060 Laptop 6 GB): 영상당 wall-clock 측정 — 5-1.임경민 (105초) baseline 측정 후 commit.
- STT (prod GPU = A6000 ×2 pool): GPU 사용률 ≥ 70% (30분 representative 윈도우, SC-010).
- nC2 분석 (200영상 = 19,900쌍): wall-clock budget는 Phase 1·2 측정 후 commit (SC-002).
- 보고서 생성 (200영상 교수 1명, PDF + HTML): wall-clock ≤ 측정 후 commit.

**Constraints**:
- Constitution V: 외부 DB 0건, 음원 임시 WAV 즉시 삭제(통합 모드) / `--keep-audio` 시만 영속.
- Constitution VI: 신규 secret 0건. faster-whisper 모델 다운로드는 `HF_HOME` / `~/.cache/huggingface/` (운영자 환경변수, agenix 무관).
- Constitution VII: §Cross-Spec Boundaries에 13개 boundary 카탈로그(B-1 ~ B-13).
- C-1 데이터 보존: 자동 retention 타이머·시간 기반 purge 미도입.
- C-2 audit logging: 단계별 분리 CSV, append-only, frozen fieldnames per stage.
- C-3 단일 의심 점수: Phase 3 출시 시점 single aggregate score 미정의 — multi-axis 정렬 + per-metric 임계 컷으로 운영.
- C-4 progress: `sys.stdout.isatty()` 분기 강제.
- C-5 retry: SQLite atomic claim 패턴.
- 자교 alias resolver(spec 003) 강제 — 미등록 채널은 ingestion 0건으로 거절.
- yt-dlp 흐름과 본 spec 흐름은 Phase 1~3 동안 코드베이스에 공존하지만 운영자는 본 spec CLI만 사용(memory `feedback_account_isolation_policy`).
- Local-only STT — 클라우드 STT API 호출 0건 (FR-048).

**Scale/Scope**:
- 1차 입력: 1 채널, 9 mp4 + 39 메타 CSV (Takeout 1차 part `3-001`)
- 채널 전체: 2,555 영상 (분할 part 누적 ingestion으로 점진 도달)
- 한 교수 영상 풀: 200영상 / 19,900쌍 nC2 (정광석 교수 기준)
- 학과 전체: 2,555 영상 × 자교 22채널 확장 시 ~56,000 영상(미래 — 본 spec 직접 검증 대상 아님)
- audio_fingerprint 테이블 외삽: 채널당 ~130 MB (spec 012 9개 영상 실측에서 외삽), 22채널 ≈ 2.9 GB
- 신규 v4 컬럼 폭증 없음 — 기존 테이블 ALTER만, 신규 row 단조 증가

---

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

### Phase 0 Gate (pre-research)

| 원칙 | 영향 | 준수 상태 | 근거 |
|---|---|---|---|
| **I. TDD (NON-NEGOTIABLE)** | 신규 모듈 (Takeout ingestion / Text Normalizer / faster-whisper wrapper / nC2 분석 미완 / 보고서 / KB export) RED → GREEN → REFACTOR | ✅ PASS | tests/contract/, tests/unit/, tests/integration/ 디렉터리 사전 정의. faster-whisper는 ctranslate2 subprocess 또는 in-process 호출이라 mocking 가능 — RED-first 강제 가능. 9개 PoC 영상 통합 테스트는 `@pytest.mark.slow` 분리. |
| **II. Fail-Fast & Anti-Hallucination** | Takeout 입력 검증 / mp4 매핑 실패 / STT 모델 다운로드 / GPU 메모리 부족 / 자막 출처 충돌 / 워커 race / 보고서 단정 라벨 검출 | ✅ PASS | 모든 실패 경로에 actionable 영문 메시지(FR-005, FR-019, FR-024, FR-058). silent skip 0건 — audit CSV에 명시 기록(C-2). faster-whisper API는 [VERIFY] 마킹 후 Phase 0 research에서 docs 확인. SQLite 트랜잭션 race는 `UPDATE ... WHERE ... RETURNING` 패턴 검증(SQLite 3.35+ 필수 — 운영자 NixOS 환경 3.45 확인). |
| **III. Type Safety + SRP** | 신규 모듈 약 10개 (`takeout_ingest`, `audio_extract`, `asr`, `text_normalizer`, `nC2_analyze`, `professor_report`, `kb_export`, `progress_reporter`, `worker_pool`, `evidence_score`) | ✅ PASS | 모든 시그니처 contracts/ 산출물(§Phase 1)로 사전 동결. SRP 분리 — ingestion(CSV 파싱 only), audio_extract(ffmpeg subprocess only), asr(faster-whisper wrapper only), normalizer(텍스트 변환 only). Google-style English docstring 강제. |
| **IV. CLI-First** | `tube-scout collect takeout/audio-extract/transcripts/process-audio`, `tube-scout process normalize-transcripts`, `tube-scout analyze content-reuse`, `tube-scout report content-reuse`, `tube-scout transcript export/export-bulk` 모두 Typer | ✅ PASS | 웹 surface 신규 0건. spec 008 admin web에 본 spec 모듈 import 없음. service-layer (services/) → CLI thin wrapper (cli/) 분리 유지. |
| **V. Local-First / DB-Free** | SQLite v4 단일 파일, JSON, CSV, Parquet (기존), 임시 WAV (Constitution V 영속 0 정책) | ✅ PASS | 외부 DB 0건. WAV 영속 0 (통합 모드 즉시 삭제). 영속 = mp4(acquisition 원본 C-1), 자막 JSON(분석 입력 C-1), SQLite, audit CSV, 보고서 산출물. faster-whisper 모델 캐시는 `~/.cache/huggingface/` 운영자 환경 — 본 spec 영속 0(B-13). |
| **VI. agenix Secrets (NON-NEGOTIABLE)** | 신규 secret 0건. STT는 로컬, captions_api는 spec 009 토큰 재사용(이미 agenix-tokens 환경변수 경유) | ✅ PASS | faster-whisper는 인증 불필요, huggingface-hub 모델 다운로드는 익명. captions_api 호출은 spec 009 토큰(`~/.config/tube-scout/tokens/`) 재사용 — boundary B-10. 신규 평문 secret 0건. |
| **VII. Cross-Spec Boundaries (NON-NEGOTIABLE)** | spec 003/006/007/009/010/011/012 + faster-whisper 모델 캐시 + 운영자 working dir + agenix + flake.nix | ✅ PASS | 본 plan §Cross-Spec Boundaries 13개(B-1 ~ B-13) 명시 + 각 항목 검증 시나리오 spec.md acceptance scenario 또는 contracts/ 매핑. 미충족 boundary 시 actionable 영문 메시지 후 거절(Principle II 일관). |

**Phase 0 Gate**: ✅ All 7 principles PASS — 연구 진행 가능.

### Phase 1 Gate (post-design)

Phase 1 산출물(data-model.md, contracts/, quickstart.md) 작성 후 동일 표 재평가 — 본 plan 하단 "Post-Design Constitution Re-check" 참조.

---

## Cross-Spec Boundaries

Principle VII NON-NEGOTIABLE — 본 spec이 공유하는 모든 경계를 1급 산출물로 동결한다. 각 항목은 (1) 이전 측 보장, (2) 본 spec 가정/생산, (3) 검증 시나리오 위치를 명시한다.

| ID | 경계 | 이전 측 보장 (prior) | 본 spec 가정 / 신규 생산 | 검증 시나리오 |
|---|---|---|---|---|
| **B-1** | spec 003 alias resolver | 자교 채널 alias → channel_id 매핑이 `tokens/channels.json` 또는 `services/professor_resolver.py`에 등록. | `collect takeout --channel <alias>` 진입 시 alias 검증, 미등록 시 actionable 메시지 후 거절. | spec.md AS-P1.1 (alias `nursing` 사용) + tests/integration/test_takeout_ingest_alias.py |
| **B-2** | spec 007 `content_reuse.db` v2 schema | `processing_status`, `fingerprint_hashes`, `comparison_results`(I-1~I-5), `quality_results`, `match_spans`, `pair_checkpoint`, `professor_pool` 등 기존 테이블 권위. | v4 migration이 기존 테이블 ALTER (`processing_status.match_confidence` / `.caption_source_detail`, `quality_results.asr_quality_flags`, `comparison_results.audio_fp_*` / `.source_type_pair`) — 기존 row preserve, 기존 컬럼 변경 0. | tests/integration/test_v4_migration.py (v3 DB → v4 적용 → 기존 row 무결성 검증) |
| **B-3** | spec 010 transcript JSON schema | `01_collect/transcripts/<video_id>.json` 형식 (`segments[].start`, `.end`, `.text`, `video_id`, `language`, `source`, `fetched_at`). | ASR 출력과 captions_api 출력 모두 동일 schema 따름. `source` enum 확장 — 기존 `api`/`ytdlp:manual`/`ytdlp:auto`에 추가 변경 없이 spec 011 호환 유지(본 spec은 source 값 신설 없음 — `whisper` 는 spec 010이 이미 보유). | tests/contract/test_transcript_json_schema.py |
| **B-4** | spec 011 분석 인프라 (`nc2_matcher`, `pair_checkpoint`, `match_spans`, `layer_defense`, `phrase_whitelist`, `baseline_corpus`, `pattern_classifier`, `time_axis_indicators`) | 부분 구현된 모듈들(spec 011 P1 미완). 시그니처는 spec 011 contracts/ 에 동결. | I-6/I-7/I-8 시간축 지표 함수 완성, M-nC2 매칭 모드 완성, 4계층 오탐 방어 완성, 4패턴 분류 + 신설 2패턴(re-recorded / tail-update) 추가. `match_spans` 테이블에 시간축 정렬 결과 영속. | tests/integration/test_nc2_analysis_full.py (9 영상 → 36쌍 end-to-end) |
| **B-5** | spec 012 `services/audit_writer.py` | spec 012가 `transcripts_audit.csv` + `fingerprint_audit.csv` 두 단계 audit를 frozen fieldnames + append-only로 운영. | C-2: 단계 8종(`takeout_ingest`, `audio_extract`, `transcripts`, `fingerprint`, `normalize`, `analyze`, `report`, `kb_export`) 각각의 frozen fieldnames 추가. Phase 4 yt-dlp 코드 삭제 시 `audit_writer.py`는 cross-stage 일반화 모듈로 유지(삭제 금지) — `services/audit_writer.py` 위치 그대로(FR-060). | tests/contract/test_audit_writer_v2.py + tests/integration/test_audit_log_pipeline.py |
| **B-6** | spec 012 `audio_fingerprint` 테이블 (SQLite v3) | `migrate_to_v3()` 완료, `insert_audio_fingerprint`/`get_audio_fingerprint` 함수 권위. | 읽기·쓰기 변경 없이 재사용. v4 migration은 본 테이블 건드리지 않음 — 신규 테이블 + 기존 테이블 ALTER만. | tests/integration/test_v3_to_v4_idempotent.py |
| **B-7** | spec 012 `services/audio_fingerprint.py` `extract_chromaprint_fingerprint(audio_path, length_seconds=0)` | mp4·wav 입력 모두 처리 가능, 9개 takeout mp4 실측 검증 완료(2026-05-12). | `fingerprint_input_policy ∈ {original_mp4, wav_16k, wav_22k}` 셋 모두 본 함수 단일로 처리. Phase 1 실측 후 기본값 commit. | tests/integration/test_fingerprint_input_policy.py (Phase 1) |
| **B-8** | spec 012 `services/srv3_parser.py`, `services/ytdlp_adapter.py`, `services/ytdlp_errors.py` | 현재 master 운영, deprecated. | Phase 1~3 동안 코드베이스에 공존(import만 발생, 본 spec 코드 흐름에서는 호출 0건). Phase 4에서 완전 삭제(FR-046). | tests/integration/test_phase4_legacy_removal.py (Phase 4) |
| **B-9** | spec 006 report bundle 인프라 (`reporting/`, jinja2 템플릿) | bundle 생성기, CSS, HTML→PDF (weasyprint) 경로 권위. | 신규 템플릿 `professor_nC2_report.html` 추가, multi-axis 정렬 + per-metric 분포 히스토그램 + top-K 목록 + 부록 1:1 페이지(C-3). 기존 보고서 템플릿(spec 004/006) 영향 0. | tests/integration/test_professor_nc2_report.py |
| **B-10** | spec 009 OAuth 토큰 (`~/.config/tube-scout/tokens/`) | 0600, agenix 무관(운영자 관리). spec 009의 `auth.py` / `auth_device_flow.py` API 권위. | 공개 영상 caption 다운로드 시 spec 009 토큰을 그대로 재사용. Takeout 외 외부 API 호출은 본 경로뿐. captions_api 실패 시 audit-log + 다음 영상 진행. | tests/integration/test_captions_api_with_oauth.py |
| **B-11** | spec 008 admin web UI | starlette / uvicorn 기반, CLI service-layer를 import 만 함(Constitution IV thin layer). | 본 spec은 web 모듈 추가 없음. ambiguous-mapping 큐 / 화이트리스트 결정의 web UI 통합은 scope OUT(Assumptions). 향후 별도 idea로 분리. | (검증 시나리오 없음 — 보지 않는 boundary, 부재 검증) |
| **B-12** | flake.nix devShell 시스템 의존성 | `chromaprint`, `ffmpeg`, `zlib`, `stdenv.cc.cc.lib` (spec 012). | 신규 추가: `cudnn`, `cuda-nvrtc` (faster-whisper GPU 런타임). 운영자 머신 NixOS 12.x 또는 unstable. | quickstart.md §환경 설정 + tests/integration/test_devshell_imports.py |
| **B-13** | huggingface-hub 모델 캐시 | 운영자 환경의 `HF_HOME` 또는 `~/.cache/huggingface/transformers/` — agenix 무관, 익명 다운로드. | faster-whisper 모델(large-v3 약 3 GB, int8 양자화 시 ~1.5 GB) 최초 1회 다운로드. 본 spec은 모델 캐시 위치를 영속 0 정책(Constitution V)에서 제외 — 운영자 환경 산출물로 간주. | quickstart.md §최초 모델 다운로드 + tests/integration/test_asr_with_cached_model.py |

**Boundary 검증 의무**: 위 13개 항목 각각에 최소 1개 acceptance scenario 또는 통합 테스트가 매핑되어 있다. B-11(spec 008 web UI)은 의도적 부재 검증(out-of-scope assertion in `quickstart.md`).

---

## Project Structure

### Documentation (this feature)

```text
specs/013-takeout-local-asr-reuse/
├── spec.md                  # /speckit.specify + /speckit.clarify 산출 (5 Clarifications)
├── plan.md                  # 본 파일 (/speckit.plan 산출)
├── research.md              # Phase 0 산출 — faster-whisper 검증, evidence score 출발점, audit_writer 재배치, progress helper
├── data-model.md            # Phase 1 산출 — channel/video_metadata + v4 migration + ASR quality flags + match_spans
├── quickstart.md            # Phase 1 산출 — 운영자 4단계 워크플로 + 디버깅 + 모델 다운로드
├── contracts/
│   ├── cli_contract.md                       # 모든 Typer 신규 명령 + 플래그 + 환경변수
│   ├── takeout_ingest_contract.md            # services/takeout_ingest.py — Evidence Score + 매핑 큐
│   ├── audio_extract_contract.md             # services/audio_extract.py — ffmpeg subprocess
│   ├── asr_contract.md                       # services/asr.py — faster-whisper wrapper + hallucination 방어
│   ├── text_normalizer_contract.md           # services/text_normalizer.py
│   ├── nc2_analyze_contract.md               # services/nc2_matcher.py + time_axis_indicators.py 완성
│   ├── professor_report_contract.md          # reporting/professor_nc2.py
│   ├── kb_export_contract.md                 # services/kb_export.py
│   ├── audit_writer_v2_contract.md           # services/audit_writer.py 8-stage 확장
│   ├── progress_reporter_contract.md         # services/progress_reporter.py — TTY/non-TTY 분기
│   ├── worker_pool_contract.md               # services/worker_pool.py — prod-a6000-pool
│   └── v4_migration_contract.md              # storage/content_db.py::migrate_to_v4
├── checklists/
│   └── requirements.md                        # /speckit.specify 산출 (이미 작성됨)
└── tasks.md                                   # /speckit.tasks 산출 (Phase 2 — 본 plan 단계에서는 생성하지 않음)
```

### Source Code (repository root)

기존 `src/tube_scout/` 구조 재사용. 본 spec 신규 모듈은 `services/` · `cli/` · `storage/` · `reporting/` 에 격리.

```text
src/tube_scout/
├── cli/
│   ├── collect.py                 # 확장: takeout / audio-extract / process-audio / transcripts --source asr
│   ├── content.py                 # 확장: analyze content-reuse --mode M-nC2 (또는 신규 analyze.py 분기)
│   ├── analyze.py                 # 확장: content-reuse subcommand 신규 (분석/보고서 분리)
│   ├── report.py                  # 확장: content-reuse subcommand 신규 (PDF/HTML 보고서)
│   ├── project.py                 # 확장: transcript export / export-bulk (또는 신규 transcript.py)
│   ├── transcript.py              # ⚠ 신규 — KB export 전담 CLI 분리 후보
│   └── progress.py                # 기존 — progress_reporter helper 의존 가능
├── services/
│   ├── takeout_ingest.py          # ⚠ 신규 — CSV 13개 파싱 + Evidence Score + 매핑 큐
│   ├── audio_extract.py           # ⚠ 신규 — ffmpeg subprocess (mp4 → 16 kHz mono wav)
│   ├── asr.py                     # ⚠ 신규 — faster-whisper wrapper + hallucination 방어
│   ├── text_normalizer.py         # ⚠ 신규 — punctuation/공백/NFC/ASR meta-marker 정규화
│   ├── worker_pool.py             # ⚠ 신규 — prod-a6000-pool dual-GPU 워커 풀
│   ├── progress_reporter.py       # ⚠ 신규 — TTY 자동 감지 rich.progress / structured log
│   ├── evidence_score.py          # ⚠ 신규 — mp4 ↔ video_id 가중치 합산 휴리스틱
│   ├── audio_fingerprint.py       # 기존 (spec 012) — 변경 0, 본 spec은 단지 호출
│   ├── audit_writer.py            # 기존 (spec 012) — 8단계 frozen fieldnames 추가 확장
│   ├── nc2_matcher.py             # 기존 (spec 011 부분) — M-nC2 완성
│   ├── time_axis_indicators.py    # 기존 (spec 011 부분) — I-6/I-7/I-8 완성
│   ├── layer_defense.py           # 기존 (spec 011) — Layer A/B/C/D 보강
│   ├── pattern_classifier.py      # 기존 (spec 011) — 6 패턴(기존 4 + 신설 2)
│   ├── srv3_parser.py             # 기존 (spec 012) — 본 spec 호출 0, Phase 4 삭제
│   ├── ytdlp_adapter.py           # 기존 (spec 012) — 동상
│   └── ytdlp_errors.py            # 기존 (spec 012) — 동상
├── storage/
│   └── content_db.py              # 확장: migrate_to_v4 함수 + channel_metadata/video_metadata 신규 테이블 + 기존 테이블 ALTER
├── reporting/
│   ├── professor_nc2.py           # ⚠ 신규 — 보고서 본문 + 부록 generator
│   └── templates/
│       └── professor_nC2_report.html  # ⚠ 신규 — jinja2 템플릿
├── models/
│   └── content.py                 # 확장: VALID_PROCESSING_STATUSES + asr_in_progress / asr_failed, ChannelMetadata / VideoMetadata Pydantic, AsrQualityFlags Pydantic
└── visualization/
    └── time_axis.py               # 확장: per-pair 시간축 프로필 차트 + alignment view

tests/
├── contract/                       # contracts/*.md 각각에 대응하는 시그니처 테스트
├── unit/                           # 모듈별 단위 테스트
├── integration/                    # B-1 ~ B-13 boundary 시나리오 + spec.md acceptance scenarios
├── perf/                           # @pytest.mark.slow — 9 영상 end-to-end, nC2 36쌍 mini
├── adversary/                      # dev-squad adversary 테스트 (Phase 4 회귀 포함)
├── fixtures/
│   ├── takeout_sample/             # 신규 — 1차 Takeout 9 mp4 + 39 CSV의 SHA-256 기반 sanitized fixture
│   └── ...
└── manual/                         # 운영자 수동 검증 시나리오 (작업 디렉터리 이전 등)
```

**Structure Decision**: 기존 단일 패키지 구조(`src/tube_scout/`) 그대로 사용. 신규 web/backend 분리 없음(Constitution IV). 신규 모듈은 `services/` 격리 + `cli/` thin wrapper + `storage/` migration 함수 추가 + `reporting/` 템플릿 1개로 완결. faster-whisper 모델 캐시는 운영자 환경(`~/.cache/huggingface/`)에 위치하므로 repo 트리 외부.

---

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

본 plan 시점에 Constitution 위반 0건. Complexity Tracking 항목 없음.

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| (none) | — | — |

---

## Post-Design Constitution Re-check

Phase 1 산출물(data-model.md, contracts/, quickstart.md) 작성 후 동일 표 재평가.

| 원칙 | Phase 0 → Phase 1 변화 | 재검사 결과 |
|---|---|---|
| **I. TDD** | contracts/ 12개 산출물이 RED-first 테스트 진입점 동결. | ✅ 유지 |
| **II. Fail-Fast & Anti-Hallucination** | research.md에서 faster-whisper API 시그니처(`WhisperModel`, `transcribe`)와 hallucination 방어 4종 옵션 실재성을 docs로 검증. SQLite `RETURNING` 절은 3.35+ 필수임을 명시(NixOS 환경 3.45). | ✅ 유지 |
| **III. Type Safety + SRP** | data-model.md에서 9개 entity Pydantic schema 동결. contracts/ 각 모듈이 SRP 단일 함수 진입점. | ✅ 유지 |
| **IV. CLI-First** | cli_contract.md에 모든 신규 Typer 명령 시그니처 동결, 웹 진입점 0건. | ✅ 유지 |
| **V. Local-First / DB-Free** | data-model.md에서 WAV 영속 0 + 모델 캐시 운영자 환경 외부 명시. | ✅ 유지 |
| **VI. agenix Secrets** | research.md에서 huggingface-hub 익명 다운로드 확인 + spec 009 OAuth 토큰 재사용 boundary 동결. 신규 secret 0건. | ✅ 유지 |
| **VII. Cross-Spec Boundaries** | 13개 B-1~B-13 항목 각각 contracts/ 또는 tests/integration/ 진입점 명시. B-11(spec 008 web UI)은 의도적 부재 검증 quickstart.md에 동결. | ✅ 유지 |

**Phase 1 Gate**: ✅ All 7 principles PASS — `/speckit.tasks` 진행 가능.
