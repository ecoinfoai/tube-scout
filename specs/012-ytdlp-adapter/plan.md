# Implementation Plan: yt-dlp 자막·음원·지문 어댑터

**Branch**: `012-ytdlp-adapter` | **Date**: 2026-05-09 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/012-ytdlp-adapter/spec.md`
**Spike**: PASS — `_workspace/spike/ytdlp_feasibility.md` (2026-05-09)
**Constitution**: v1.1.0 (`.specify/memory/constitution.md`)
**Target Release**: v0.4.0 (spec 011 + spec X1 동반 출시 — pyproject.toml `0.3.3 → 0.4.0`)

## Summary

22채널 약 4,000편 강의 영상의 ASR 자막을 YouTube Data API quota 없이 yt-dlp + cookies-from-browser 경로로 백필하고, 같은 흐름에서 chromaprint 음향 지문을 영속 저장하여 spec Y(음향 매칭, 미래) 의 read-only 입력으로 동결한다. 모든 흐름은 자교 22채널 alias resolver(spec 003)에 한정되며 외부 채널은 yt-dlp 호출 0건으로 거절된다. 음원 파일은 추출 후 60초 내 자동 삭제되어 영구 보관 0 정책을 코드로 보장한다.

기술 접근(spike 확정): yt-dlp `--write-subs` + `--write-auto-subs` 양쪽 호출 후 manual 우선 → auto fallback, srv3 → spec 010 transcript JSON 변환, 음원 22050Hz mono mp3 → fpcalc subprocess(audioread 백엔드 의존 회피) → chromaprint 지문 b64 BLOB 저장. 통합점 9개(B-X1-1~9)는 §Cross-Spec Boundaries에 카탈로그.

## Technical Context

**Language/Version**: Python 3.11 (pinned via `flake.nix` devShell + `pyproject.toml`)

**Primary Dependencies**:
- 신규 (PyPI): `yt-dlp` (caption + audio fetch), `pyacoustid` (chromaprint Python 모듈만 사용 — `fingerprint_file()` 미사용, audioread 백엔드 의존 회피)
- 신규 (Nix system): `chromaprint`(libchromaprint.so + fpcalc CLI), `ffmpeg-full`, `zlib`, `stdenv.cc.cc.lib`(libstdc++ LD)
- 기존 재사용: `typer`, `rich`, `pydantic v2`, `polars`(read-only consume from spec 011), `subprocess` stdlib

**Storage**:
- 자막: JSON (`projects/{job-id}/01_collect/transcripts/{vid}.json`) — spec 010 형식 그대로 (B-X1-1)
- 지문: SQLite v3 (`projects/{job-id}/02_analyze/content/content_reuse.db`) — spec 011 v2 위에 `audio_fingerprint` 테이블 ALTER 추가 (B-X1-2)
- 임시 음원: `projects/{job-id}/01_collect/audio_temp/{vid}.mp3` (lifecycle: extract → fingerprint → delete, 영구 보관 0)
- Audit CSV: `projects/{job-id}/01_collect/transcripts_audit.csv`, `fingerprint_audit.csv`

**Testing**: `pytest`, `pytest-asyncio`(기존), `@pytest.mark.slow`(rate-limit 50-URL 검증, dev-squad 결정)

**Target Platform**: NixOS Linux (운영자 머신 + cron) + 일반 Linux (CI), Python 3.11 단일

**Project Type**: CLI tool (Typer) — Constitution IV CLI-First. 웹 surface 없음 (spec 008 admin web은 본 spec 흐름 import 없음)

**Performance Goals**:
- 영상 1편당 wall-clock ≤ 60초 (자막 ~1초 + 음원 ~12초 + 지문 ~1초 + sleep 30~60초). spike 측정.
- 22채널 × 4,000편 전수 백필 1회 ≈ 67시간 (채널별 시차 cron으로 분산 가능)
- fpcalc subprocess startup overhead ≤ 100ms (spike 측정 < 1초/33분 영상)

**Constraints**:
- NixOS LD_LIBRARY_PATH 4종 강제 export (libchromaprint + libstdc++ + libz + ffmpeg). devShell shellHook이 자동 처리 — 운영자 수동 설정 0.
- Brave keyring unlocked 가정 (spike 검증), locked 시 cookies.txt 폴백 자동 전환.
- Constitution VI: cookies는 0600 + 환경변수 참조, 평문 repo commit 금지. 디폴트 `--cookies-from-browser brave`는 agenix 의존 0 (호스트 keyring 직접).
- Constitution V: 음원 파일 영구 0, audit CSV·지문 BLOB만 영속.

**Scale/Scope**:
- 22 등록 자교 채널 (spec 003 alias resolver)
- ~4,000 영상 (현재 추정, 신규 영상은 weekly cron으로 점증)
- 비공개 88.6% (~3,544편) + 일부공개 6~11% (~440편) — 공개 0%
- audio_fingerprint 테이블 예상 총량 ~5.5 GB (영상 1분당 ~2 KB × 평균 25분 × 4,000편)
- 자막 부재 ~24편 (지문만 영속, 자막 단계 audit-log)

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

### Phase 0 Gate (pre-research)

| 원칙 | 영향 | 준수 상태 | 근거 |
|---|---|---|---|
| **I. TDD (NON-NEGOTIABLE)** | 모든 신규 함수 RED → GREEN → REFACTOR | ✅ PASS | dev-squad workflow는 RED-first 강제. tests/contract/, tests/unit/, tests/integration/ 디렉터리 사전 정의(§Project Structure) |
| **II. Fail-Fast & Anti-Hallucination** | yt-dlp / fpcalc / cookies / 인증 실패 처리 | ✅ PASS | 모든 실패 경로에 actionable 영문 메시지 (FR-016, FR-017, FR-018). silent skip 0건 — audit CSV로 명시 기록. yt-dlp/chromaprint API는 spike에서 실측 검증 (hallucination 0) |
| **III. Type Safety + SRP** | 신규 모듈 3개 (srv3_parser / ytdlp_adapter / audio_fingerprint) | ✅ PASS | 모든 시그니처 spike 산출물(idea §4.2)로 사전 확정. SRP 분리 — srv3_parser(파싱 only), ytdlp_adapter(I/O only), audio_fingerprint(subprocess + decode only). Google-style English docstring 강제 |
| **IV. CLI-First** | `tube-scout collect transcripts/audio/fingerprint` Typer 확장 | ✅ PASS | service-layer (services/) → CLI thin wrapper (cli/collect.py). 웹 surface 신규 0건. spec 008 admin web은 영향 0 |
| **V. Local-First / DB-Free** | SQLite v3 (단일 파일), JSON, CSV | ✅ PASS | 외부 DB 0건. 음원 파일 즉시 삭제 (FR-009, SC-004). 영속 = 지문 BLOB + audit CSV + transcript JSON 만 |
| **VI. agenix Secrets (NON-NEGOTIABLE)** | cookies 관리 | ✅ PASS | 디폴트는 호스트 keyring (agenix 의존 0). 폴백은 `TUBE_SCOUT_COOKIES_FILE` 환경변수 (agenix 적용 가능) 또는 0600 로컬 파일. 평문 repo commit 금지(.gitignore 추가). 신규 secret 0건 (디폴트 path) |
| **VII. Cross-Spec Boundaries (NON-NEGOTIABLE)** | spec 003/009/010/011 + spec Y(미래) + agenix + flake.nix | ✅ PASS | spec.md §Cross-Spec Boundaries 9개(B-X1-1~9) 명시 + 각 항목 검증 시나리오 매핑. 미충족 boundary 시 yt-dlp 호출 0건 거절 (FR-019) — Principle II와 일관 |

**Phase 0 Gate**: ✅ All 7 principles PASS — 연구 진행 가능.

### Post-Phase 1 Gate

Phase 1 산출물(data-model.md, contracts/, quickstart.md) 작성 후 동일 표 재평가 — 본 plan 하단 "Post-Design Constitution Re-check" 참조.

## Project Structure

### Documentation (this feature)

```text
specs/012-ytdlp-adapter/
├── spec.md                  # /speckit.specify + /speckit.clarify 산출
├── plan.md                  # 본 파일 (/speckit.plan 산출)
├── research.md              # Phase 0 산출 — spike 결과 + 외부 베스트 practice 통합
├── data-model.md            # Phase 1 산출 — 5 entity + audio_fingerprint v3 schema
├── quickstart.md            # Phase 1 산출 — 운영자 cron + 디버깅 워크플로
├── contracts/
│   ├── ytdlp_adapter_contract.md      # 함수 시그니처 + 입출력 + 에러 패턴
│   ├── srv3_parser_contract.md
│   ├── audio_fingerprint_contract.md
│   └── cli_contract.md                 # Typer 명령 + 플래그 + 환경변수
├── checklists/
│   └── requirements.md                  # /speckit.specify 산출
└── tasks.md                             # /speckit.tasks 산출 (Phase 2 — 본 plan 단계에서는 생성하지 않음)
```

### Source Code (repository root)

기존 구조 (`src/tube_scout/`) 재사용. 본 spec 신규 모듈은 `services/`에 격리, CLI는 `cli/collect.py`에 확장, schema migration은 `storage/content_db.py`에 v3 함수 추가.

```text
src/tube_scout/
├── services/
│   ├── ytdlp_adapter.py             # NEW — yt-dlp subprocess wrapper (caption / audio)
│   ├── srv3_parser.py                # NEW — srv3 XML → spec 010 transcript JSON
│   ├── audio_fingerprint.py          # NEW — fpcalc subprocess + chromaprint decode + similarity
│   ├── audit_writer.py               # NEW — atomic CSV append for transcripts/fingerprint audit (FR-015)
│   ├── ytdlp_errors.py               # NEW — 8 exception classes (Constitution II)
│   ├── fingerprint.py                # EXISTING (텍스트 SHA-256 — spec 011) — 변경 0, B-X1-9 격리
│   ├── secret_loader.py              # EXISTING — cookies env var loader 확장 시 import
│   ├── auth.py                       # EXISTING — alias 해석 `resolve_channel_alias()` + `load_registry()` (spec 009, B-X1-4)
│   └── ...                           # 기타 기존 모듈 — 변경 0
├── cli/
│   └── collect.py                    # MODIFY — `--source {api|ytdlp}` flag, `--all-channels` flag,
│                                     #          `collect audio`, `collect fingerprint` 신규 subcommands
├── storage/
│   └── content_db.py                 # MODIFY — `migrate_to_v3()` + `audio_fingerprint` table API
├── models/
│   └── audio_fingerprint.py          # NEW (옵션) — pydantic v2 model for typed access (검토 후 결정)
└── ...

tests/
├── contract/
│   └── test_ytdlp_adapter_contract.py # NEW — 시그니처 + 반환 형식 + 에러 패턴 RED-first
├── unit/
│   ├── test_srv3_parser.py            # NEW — 7개 시나리오 (manual / auto / a="1" skip / 빈 <p> /
│   │                                  #         empty body / malformed XML / encoding 변환)
│   ├── test_audio_fingerprint.py      # NEW — fpcalc subprocess mock + decode + hamming
│   ├── test_ytdlp_adapter.py          # NEW — cookies fallback chain + sleep + idempotent skip
│   ├── test_collect_cli.py            # NEW — --source / --all-channels / 환경변수 우선순위
│   └── test_content_db_v3.py          # NEW — v2→v3 ALTER idempotent + audio_fingerprint CRUD
└── integration/
    ├── test_ytdlp_caption_flow.py     # NEW — fixture srv3 (spike 산출물) → JSON 변환 → spec 010 호환 검증
    ├── test_audio_fingerprint_flow.py # NEW — fixture mp3 → fpcalc → DB → 음원 삭제 lifecycle
    ├── test_ytdlp_rate_limit.py       # NEW — @pytest.mark.slow, 5-URL × 30s sleep boundary 측정 (dev-squad opt-in)
    └── test_cross_spec_boundary.py    # NEW — B-X1-1 ~ B-X1-7 통합 검증 (Constitution VII)
```

**Structure Decision**: Single project (Python 3.11 CLI). 기존 `src/tube_scout/` layer 분리 (services / cli / storage / models) 그대로 활용. 신규 추가 3 module + 1 modify(collect.py) + 1 modify(content_db.py). 텍스트 fingerprint(spec 011)와 음향 fingerprint(본 spec)는 다른 모듈로 격리(B-X1-9).

## Phase 0 — Research

상세 산출물: [research.md](./research.md) (Phase 0 — 본 명령 직후 작성).

**Phase 0 핵심 입력**:
1. spike 결과 (`_workspace/spike/ytdlp_feasibility.md`) — yt-dlp 2026.03.17 / chromaprint 1.6.0 / ffmpeg 8.0.1 의 실측 동작
2. spec 010 transcript JSON 형식 (코드 + spec.md 권위)
3. spec 011 `content_reuse.db` v2 schema (코드 + spec.md 권위)
4. spec 003 alias resolver 시그니처 (services 레이어)
5. yt-dlp 옵션 매뉴얼 (특히 `--write-subs` vs `--write-auto-subs`, `--postprocessor-args ffmpeg:` prefix, `--cookies-from-browser`, `--sleep-subtitles`)

**Phase 0 결정 사항** (research.md에서 상세):
- 시그니처 9개 함수 (idea §4.2 + clarify Q2 manual 우선 반영) — fetch_caption_via_ytdlp / srv3_to_transcript_json / fetch_audio_via_ytdlp / extract_chromaprint_fingerprint / decode_fingerprint_to_array / hamming_distance_per_int / best_alignment_hamming + collect CLI 2개
- pyacoustid는 PyPI 패키지로 import만 사용 (chromaprint 모듈), `fingerprint_file()` 호출 0 — audioread 백엔드 의존 회피
- yt-dlp `postprocessor-args` ffmpeg: prefix 강제 (spike 확정)
- audit CSV 컬럼 sequence 동결 (B-X1-7 — 운영자 컴플라이언스 검증용)
- v3 schema migration: ALTER `CREATE TABLE IF NOT EXISTS audio_fingerprint (...)` idempotent + 기존 v2 컬럼·테이블 변경 0

**NEEDS CLARIFICATION**: 0건. spike + clarify Q1~Q5로 모든 unknowns 해소.

## Phase 1 — Design & Contracts

상세 산출물:
- [data-model.md](./data-model.md) — 5 entity + audio_fingerprint v3 DDL + spec 010/011 boundary diff
- [contracts/](./contracts/) — 4 contract 파일 (ytdlp_adapter / srv3_parser / audio_fingerprint / cli)
- [quickstart.md](./quickstart.md) — 운영자 cron + 디버깅 + 인증 갱신 워크플로

### Phase 1 산출물 개요

**data-model.md 핵심**:
- `audio_fingerprint` 테이블 DDL (PK video_id, fingerprint BLOB, duration REAL, extracted_at TEXT ISO8601, source TEXT 'fpcalc:1.6.0' for forward compat)
- 5 entity 클래스 시그니처 (Transcript / Audio Temp File / Audio Fingerprint / Cookies Source / Audit Record)
- spec 011 v2 → v3 migration step-by-step + idempotent 보장 SQL

**contracts/ 핵심**:
- `ytdlp_adapter_contract.md`: `fetch_caption_via_ytdlp()`, `fetch_audio_via_ytdlp()` 시그니처 + 6 에러 시나리오 (no captions / cookies expired / keyring locked / rate limit 429 / network / live_or_premiere)
- `srv3_parser_contract.md`: `srv3_to_transcript_json()` + 7 단위 테스트 시나리오 (manual / auto / a="1" / 빈 <p> / empty body / malformed / encoding)
- `audio_fingerprint_contract.md`: `extract_chromaprint_fingerprint()` + `decode_fingerprint_to_array()` + `hamming_distance_per_int()` + `best_alignment_hamming()` + 5 시나리오 (정상 / fpcalc fail / 음원 부재 / 30s 미만 / 인코딩 미지원)
- `cli_contract.md`: `tube-scout collect transcripts --source --all-channels` + `collect audio --all-channels` + `collect fingerprint --all-channels` + 3 환경변수 + 8 exit code 패턴

**quickstart.md 핵심**:
- 운영자 1회 셋업 (`uv sync`, devShell 진입, Brave 로그인 확인, 22채널 alias 등록 확인)
- weekly cron 스크립트 1쪽 (4 collect 명령 × `--all-channels`)
- 디버깅 (`transcripts_audit.csv` 검사, `fingerprint_audit.csv` 검사, cookies 갱신, rate limit 회복)
- 트러블슈팅 (Brave keyring locked / cookies.txt 수동 export / fpcalc subprocess 실패 / NixOS LD 환경변수 누락)

### Agent Context Update

`.specify/scripts/bash/update-agent-context.sh claude` 를 본 plan 단계 마지막에 실행 — `CLAUDE.md` 의 "Active Technologies" 에 yt-dlp + chromaprint + audio fingerprint 항목 자동 추가.

## Post-Design Constitution Re-check

Phase 1 산출(`data-model.md` / `contracts/*.md` 4건 / `quickstart.md`) 작성 완료 → 재평가:

| 원칙 | Phase 0 → Phase 1 변화 | 최종 상태 |
|---|---|---|
| **I. TDD** | contracts/ 시나리오 (전체 35개: ytdlp_adapter 8 + srv3_parser 7+4 + audio_fingerprint 9+4 + cli 12 + integration 4) → tests/* RED-first 1:1 매핑 검증됨 | ✅ PASS |
| **II. Fail-Fast** | contracts/ 에 8 exception type + 24 raise site + 8 exit code 패턴 명시. 모든 메시지 actionable English. | ✅ PASS |
| **III. Type Safety + SRP** | data-model.md 5 entity + 9 함수 시그니처 동결. SRP — srv3_parser(parse only) / ytdlp_adapter(I/O only) / audio_fingerprint(subprocess+decode only) / cli/collect.py(thin wrapper). | ✅ PASS |
| **IV. CLI-First** | cli_contract.md 의 모든 명령은 services/ 레이어 호출 — 역방향 dep 0. quickstart.md 가 CLI-only 운영 시나리오 명시. | ✅ PASS |
| **V. Local-First** | data-model.md DDL = SQLite v3 단일 파일. audio_temp lifecycle 명시 (영속 0). audit CSV append-only. | ✅ PASS |
| **VI. agenix** | cli_contract.md 환경변수 3개 (`TUBE_SCOUT_DEFAULT_TRANSCRIPT_SOURCE`, `TUBE_SCOUT_COOKIES_FILE`, `TUBE_SCOUT_COOKIES_BROWSER`) 모두 agenix 호환. cookies file 0600 강제 (resolve_cookies_source). 평문 git commit 차단 (.gitignore 추가). | ✅ PASS |
| **VII. Cross-Spec** | spec.md §Cross-Spec Boundaries 9개 (B-X1-1~9) + contracts/ 각 파일 boundary references 매핑 + quickstart.md operator self-audit 6 invariants. 통합 테스트 `test_cross_spec_boundary.py` 신규. | ✅ PASS |

**Post-Design Gate**: ✅ All 7 principles PASS — `/speckit.tasks` 진입 가능.

## Complexity Tracking

> **Constitution Check 위반 0건 — 본 섹션 비움 (justify 불필요)**

| Violation | Why Needed | Simpler Alternative Rejected Because |
|---|---|---|
| (없음) | (없음) | (없음) |

## Estimated Effort

| 단계 | 작업 시간 | 산출물 |
|---|---|---|
| Phase 0 — research.md | 30~45분 (본 plan 직후) | research.md (~150줄) |
| Phase 1 — data-model + contracts + quickstart | 1~1.5시간 | 4 contracts + data-model + quickstart |
| `/speckit.tasks` | 30~45분 | tasks.md (~30~40 task, TDD 정렬) |
| dev-squad 구현 | 5~7일 | 신규 3 module + 2 modify + 9 test 파일 + flake.nix patch + content_db v3 migration |
| QA + adversary + auditor | 1~2일 (dev-squad 병행) | adversary 매트릭스, 보안 보고서, 회귀 회로 |
| **총 spec X1 완료까지** | **약 1주 (5~7 영업일)** | v0.4.0 출시 트리거 |

## References

- spec.md (본 spec) — `specs/012-ytdlp-adapter/spec.md`
- spike 보고서 — `_workspace/spike/ytdlp_feasibility.md`
- idea doc — `idea/idea-2026-05-09-spec-X1-ytdlp-adapter.md`
- Constitution v1.1.0 — `.specify/memory/constitution.md`
- spec 010 (transcript JSON 형식 권위) — `specs/010-prefer-captions-resume/spec.md`
- spec 011 (`content_reuse.db` v2 schema 권위) — `specs/011-reuse-fullstack-subtitle/spec.md`
- spec 003 (`--channel <alias>` resolver 권위) — `specs/003-multichannel-admin/spec.md`
- spec 009 (OAuth token 별개 흐름 권위) — `specs/009-runtime-auth-fix/spec.md`
