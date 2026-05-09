# Feature Specification: yt-dlp 자막·음원·지문 어댑터

**Feature Branch**: `012-ytdlp-adapter`
**Created**: 2026-05-09
**Status**: Draft
**Target Release**: v0.4.0 (운영자 결정, spec 011 + spec X1 동반 출시)
**Spike**: PASS (`_workspace/spike/ytdlp_feasibility.md`, 2026-05-09)
**Idea Doc**: `idea/idea-2026-05-09-spec-X1-ytdlp-adapter.md`
**Input**: User description: "yt-dlp 자막·음원·지문 어댑터 — 22채널 ASR 백필을 YouTube Data API quota에 의존하지 않도록 yt-dlp + cookies-from-browser 경로 도입, 비공개 영상 자막 fetch + 음원 추출 + chromaprint 지문(spec Y 베이스) 통합."

## Clarifications

### Session 2026-05-09

- Q: 지문 수집(`collect fingerprint`) 디폴트 scope? → A: 전 영상 (채널 전체, 30초 미만만 스킵)
- Q: 자막 manual(수동) vs auto(ASR) 처리 정책? → A: Manual 우선, manual 부재 시 auto fallback. source 필드 `ytdlp:manual` 또는 `ytdlp:auto`로 구분
- Q: Cookies.txt 폴백 경로 + provisioning 정책? → A: 환경변수 `TUBE_SCOUT_COOKIES_FILE` 우선, 미설정 시 디폴트 경로 `~/.config/tube-scout/cookies.txt`(0600), 둘 다 부재 시 actionable 메시지로 수동 export 안내
- Q: `collect transcripts` 디폴트 `--source` 값? → A: 환경변수 `TUBE_SCOUT_DEFAULT_TRANSCRIPT_SOURCE` (api/ytdlp) 결정, 미설정 시 `api` (spec 010 backward compat). 운영자는 `.envrc`/cron에 한 줄 추가로 토글
- Q: 22채널 batch CLI 패턴? → A: 각 `collect` 명령(videos/transcripts/audio/fingerprint)에 `--all-channels` 플래그 추가. `--channel <alias>` 는 디버깅·테스트용으로 유지. 채널별 실패 isolation 코드 레벨 보장

## User Scenarios & Testing *(mandatory)*

### User Story 1 — 22채널 ASR 자막 백필 (Priority: P1)

운영자(DX센터장)가 YouTube Data API quota 승인을 기다리지 않고도 자교 22채널 약 4,000편 강의 영상의 자동 생성(ASR) 한국어 자막을 일괄 수집할 수 있다. 비공개(Unlisted/Private) 88.6% 영상까지 본인 인증된 브라우저 쿠키로 동일하게 수집된다.

**Why this priority**: 본 spec의 1차 동기. spec 010이 마련한 transcript pipeline이 quota 의존성 때문에 멈춰있는 상태를 해소하는 단일 핵심 가치. 본 스토리만 구현해도 spec 011 (재사용 탐지)이 22채널 전수 데이터로 작동 가능 — MVP 자격.

**Independent Test**: 운영자가 한 채널(예: nursing)에 대해 자막 백필 명령을 실행하면, 채널 전체 영상(일부공개 + 비공개 혼합)의 자막이 spec 010 호환 형식으로 저장되고, Data API quota 사용량은 0 unit으로 기록된다. 자막이 본 spec 이전에 수집된 영상은 다시 받지 않는다(idempotent).

**Acceptance Scenarios**:

1. **Given** 운영자가 본인 인증된 Brave 브라우저로 YouTube에 로그인 상태이고 자교 채널 alias `nursing` 이 등록되어 있을 때, **When** `tube-scout collect transcripts --source ytdlp --channel nursing` 을 실행하면, **Then** 채널의 모든 신규 영상에 대해 자막 파일이 spec 010 transcript JSON 형식으로 저장되며, 일부공개·비공개 구분 없이 동일 흐름으로 처리된다.
2. **Given** 동일 채널에 자막이 이미 수집된 영상이 있을 때, **When** 같은 명령을 재실행하면, **Then** 기존 영상은 스킵되고 신규 영상만 처리되며 (skip-existing), 처리된 영상 수와 스킵된 영상 수가 보고된다.
3. **Given** 운영자가 22채널 alias 목록을 한 번에 처리하는 cron 스크립트를 실행할 때, **When** 어느 한 채널에서 인증 만료가 발생하면, **Then** 해당 채널만 actionable 영문 메시지("Brave keyring is locked. Run `tube-scout auth refresh-cookies` and re-run.")와 함께 audit-log되고 나머지 채널은 정상 진행된다.

---

### User Story 2 — 자막 부재 영상 음향 지문 영속화 (Priority: P2)

운영자는 자막이 비활성화된 영상(~24편) 또는 향후 ASR 부정확이 의심되는 영상에 대해 음원에서 음향 지문을 추출하여 영속 저장한다. 추후 음향 매칭(spec Y)의 입력이 되어, 자막만으로 탐지 불가능한 같은 슬라이드 다른 음성(재녹음) / 자막 부재 강의도 재사용 후보로 분석할 수 있게 된다.

**Why this priority**: spec 011의 한계(자막 부재 + ASR 노이즈 false positive)를 해결하는 음향 신호 베이스. 본 spec X1이 production 형식을 fix해두어야 spec Y(향후)가 read-only 로 소비할 수 있다. P1 자막만으로는 22채널 전수 분석 불가능한 영상이 남기 때문에 P2.

**Independent Test**: 한 채널의 자막 없는 영상 5편 또는 30초 이상 임의 영상에 대해 지문 명령을 실행하면, 영상 1편당 음원이 임시 파일로 추출되어 chromaprint 지문이 SQLite 테이블에 저장되고, 음원 파일은 60초 내 자동 삭제된다. 지문 만으로 self-hamming = 0 (sanity), 다른 영상과의 hamming distance 가 측정 가능하다.

**Acceptance Scenarios**:

1. **Given** 채널 alias `nursing` 의 영상 N편이 등록되어 있고 음원·지문이 수집되지 않은 상태일 때, **When** `tube-scout collect fingerprint --channel nursing` 을 실행하면, **Then** 30초 이상 영상 각각에 대해 음원이 임시 추출 → chromaprint 지문 산출 → DB 영속 → 음원 즉시 삭제 가 일어나고, 30초 미만 영상은 스킵된다.
2. **Given** 동일 채널에 지문이 이미 수집된 영상이 있을 때, **When** 같은 명령을 재실행하면, **Then** 기존 영상은 스킵되고 신규 영상만 처리된다 (idempotent).
3. **Given** 명령 실행 도중 운영자가 Ctrl+C 등으로 중단할 때, **When** 임시 음원 파일이 남아있는 경우, **Then** 다음 실행 시 시작 시점에 임시 파일이 자동 정리되거나 명시적 actionable 메시지가 출력된다(음원 영구 보관 0 정책 보장).

---

### User Story 3 — 자교 채널 ToS 준수 + 음원 영구 보관 0 (Priority: P3)

운영자(자교 채널 owner)만이 자기 백업 정당성으로 yt-dlp 흐름을 사용하며, 다른 사람·외부 채널 영상에 대해서는 본 명령이 거절된다. 추출된 음원은 어떤 경우에도 영속 저장되지 않으며, 운영자가 검증할 수 있는 audit 신호가 남는다.

**Why this priority**: Constitution V (local-first / 외부 의존 최소) + roadmap §5.2 (자교 자기 백업 ToS 정당성) + PS-A-12 (외부 채널 영구 scope OUT) 준수. P1·P2 가치를 손상시키지 않으면서 운영 정책이 코드로 보장돼야 신뢰 가능. 영속 가치는 P3이지만 누락 시 컴플라이언스 사고로 직결.

**Independent Test**: 외부 채널 URL 또는 자교 alias 가 아닌 channel_id 를 인자로 주면 명령이 즉시 거절된다(exit code != 0, 영문 actionable 메시지). audit 로그에 처리된/스킵된/실패 영상 ID + 사유가 기록되어 운영자가 컴플라이언스 검증할 수 있다.

**Acceptance Scenarios**:

1. **Given** 운영자가 alias 목록에 등록되지 않은 임의 channel_id를 명령에 전달할 때, **When** `tube-scout collect transcripts --source ytdlp --channel <unknown>` 을 실행하면, **Then** 명령이 즉시 거절되고("Channel alias '<unknown>' not registered. External channels are out of scope. See `tube-scout admin channel add` to register a self-owned channel."), 어떤 yt-dlp 호출도 발생하지 않는다.
2. **Given** P2 명령이 정상 실행되어 임시 음원 디렉터리에 파일이 생성되었다가 삭제될 때, **When** 명령이 종료된 직후 `01_collect/audio_temp/` 디렉터리를 점검하면, **Then** 디렉터리는 비어있거나(정상 종료) 명시적 audit 항목이 남아있다(비정상 종료).
3. **Given** P1·P2 명령이 처리한 영상 목록을 운영자가 검증하고 싶을 때, **When** `<project>/01_collect/transcripts_audit.csv` (자막) 또는 `<project>/01_collect/fingerprint_audit.csv` (지문) 을 열면, **Then** 영상 ID, 처리 결과(success/skip/fail), 사유, 타임스탬프, 사용된 cookies 출처(brave/file)가 기록되어 있다.

---

### Edge Cases

- **Live stream / premiere 영상**: yt-dlp 가 finalized 안 된 영상으로 인식 → 자동 스킵 + audit-log "live_or_premiere"
- **30초 미만 영상**: chromaprint 신뢰성 부족 → 지문 단계에서 스킵 + audit-log "too_short" (자막 단계는 정상 처리)
- **2시간 초과 영상**: 음원 파일 크기 ~120MB 도달 가능 → 처리는 진행하되 WARN 로그 + audit-log "long_form"
- **Brave keyring locked / cookies-from-browser 디크립션 실패**: cookies.txt fallback 가능 여부 점검 → 둘 다 실패 시 actionable 메시지 + 명령 종료(0이 아닌 exit)
- **Cookies 만료 (HTTP 401/403)**: actionable 메시지 ("YouTube cookies expired. Re-login in Brave and re-run.") + 해당 채널 종료, 다른 채널 진행
- **HTTP 429 rate limit**: 디폴트 sleep 30~60초 random 사이에 발생 시 exponential backoff (60s → 300s → 1800s, 최대 3회) 후 actionable 메시지 + 종료
- **음원 인코딩 미지원** (특정 코덱): per-video 스킵 + audit-log "audio_decode_failed" + 다음 영상 진행
- **자막 트랙 없음** (manual + auto 모두 부재): per-video 스킵 + audit-log "no_captions_available" + 다음 영상 진행 (P2 지문 단계는 별개로 진행)
- **이미 수집된 영상 재처리 요청**: 디폴트 idempotent skip. `--force` 플래그로만 덮어쓰기 허용
- **Ctrl+C 또는 SIGTERM 중단**: 임시 음원 디렉터리 정리 시도 + 진행 중 영상은 audit-log "interrupted", 다음 실행에서 자동 재개
- **외부 채널 video URL 직접 전달**: 거절 + actionable 메시지, yt-dlp 호출 0건

## Cross-Spec Boundaries *(Constitution VII — NON-NEGOTIABLE)*

| # | 상대 spec / 시스템 | 공유 자산 | 사전 측 보장 | 본 spec 가정 / 신규 산출 | 검증 시나리오 |
|---|---|---|---|---|---|
| B-X1-1 | spec 010 (`prefer-captions-resume`) | `01_collect/transcripts/{vid}.json` 형식 | spec 010 transcript JSON 형식 권위 — `{video_id, language, source, segments:[{start, end, text}]}` | yt-dlp srv3 → 동일 형식 변환(`srv3_parser`). source 값 `ytdlp:manual` / `ytdlp:auto` 신규 추가 | Story 1 Acceptance #1 + SC-007 (spec 011 파이프라인이 본 spec transcript JSON 추가 변환 0건 소비) |
| B-X1-2 | spec 011 (`reuse-fullstack-subtitle`) | `02_analyze/content/content_reuse.db` v2 schema | spec 011 schema 권위 (videos / segments / matches 등) | 신규 테이블 `audio_fingerprint` v3 ALTER 추가, 기존 컬럼·테이블 변경 0 (idempotent migration) | Story 2 Acceptance #1 + 통합 테스트 v2→v3→v2 round-trip migration |
| B-X1-3 | spec Y (음향 매칭, 미래 v0.6+) | `audio_fingerprint` 테이블 read-only | 본 spec이 production 형식 fix (PK / BLOB / REAL / ISO8601 timestamp) | 시그니처 동결 — v3 schema는 이후 ALTER로만 확장 (필드 삭제·이름 변경 0). spec Y는 LSH 인덱스 등 read-only 보조 테이블만 추가 | dev-squad 단위에서 schema 정의 확정 + spec Y placeholder 테스트 (read-only consume 시뮬레이션) |
| B-X1-4 | spec 003 (`multichannel-admin`) | `--channel <alias>` resolver | alias → channel_id resolver 권위 | 본 spec의 yt-dlp 흐름은 resolver를 거쳐서만 video URL 산출. 미등록 alias는 yt-dlp 호출 0건으로 거절 (PS-A-12 강제) | Story 3 Acceptance #1 + SC-008 (외부 채널 0건) |
| B-X1-5 | spec 009 (`runtime-auth-fix`) | OAuth 토큰 (`~/.config/tube-scout/tokens/{alias}.json`) | spec 009 Data API 인증 권위 | yt-dlp 경로는 OAuth 미사용 (cookies). 단 `--source api` 폴백 시 spec 009 토큰 재사용 — 본 spec은 토큰 형식·경로 변경 0 | 통합 테스트: `--source api` 흐름 spec 009 mock token, `--source ytdlp` 흐름 cookies — 두 path 양쪽 동시 작동 |
| B-X1-6 | agenix secret store | YouTube cookies | Constitution VI — 환경변수 참조, 평문 저장 0, 0600 권한 | 디폴트는 `--cookies-from-browser brave`(호스트 keyring 직접, agenix 의존 0). 폴백 시만 `TUBE_SCOUT_COOKIES_FILE` 환경변수 또는 `~/.config/tube-scout/cookies.txt`(0600) | Story 1 Acceptance #3 (인증 만료 actionable + 채널 isolation) + 단위 테스트 cookies 부재 시 actionable 종료 |
| B-X1-7 | 출력 디렉터리 컨벤션 | `projects/{job-id}/01_collect/...` | Constitution V — `YYYYMMDD-HHMMSS[-N]` job-id, 분리 트리 금지 | 기존 `01_collect/transcripts/` 그대로 + 신규 임시 `01_collect/audio_temp/` (처리 후 폐기 보장) + 신규 audit `01_collect/transcripts_audit.csv`, `fingerprint_audit.csv` | Story 3 Acceptance #2,3 + SC-004 (audio_temp 잔재 0건) |
| B-X1-8 | flake.nix devShell | NixOS 빌드 환경 | spec 0xx devShell 누적 의존성 | 신규 의존성 5건 추가: `yt-dlp`, `chromaprint`, `ffmpeg`, `zlib`, `stdenv.cc.cc.lib`. devShell `shellHook` 에 `LD_LIBRARY_PATH` 자동 export — 기존 시 LD 변수 영향 0 (덮어쓰기 0) | spike 검증 완료 (`_workspace/spike/ytdlp_feasibility.md` Step 0/5) + Plan 단계 구체 패치 |
| B-X1-9 | spec 011 services/fingerprint.py | 텍스트 SHA-256 fingerprint module | spec 011 module은 캡션 텍스트 해시 권위 — 본 spec과 이름 충돌 가능 | 신규 module 이름은 `services/audio_fingerprint.py` (별도 SRP). 텍스트 fingerprint 영향 0 | 단위 테스트 양쪽 모듈 import 동시 검증 |

## Requirements *(mandatory)*

### Functional Requirements

**Caption fetch (P1)**:

- **FR-001**: 시스템은 자교 등록 채널 alias에 한해 yt-dlp 경로로 자막을 수집해야 하며, 외부 채널·미등록 alias 요청은 즉시 거절해야 한다.
- **FR-002**: 시스템은 운영자 본인 인증된 브라우저 쿠키(디폴트: Brave)를 사용하여 일부공개·비공개 영상 자막을 동일 흐름으로 수집해야 한다.
- **FR-003**: 시스템은 yt-dlp가 산출한 srv3 자막을 spec 010 transcript JSON 형식(`{video_id, language, source, segments:[{start, end, text}]}`)으로 변환하여 저장해야 한다 (spec 010 boundary B-3 호환).
- **FR-004**: 시스템은 한국어 자막(`ko`, `ko-orig`)을 yt-dlp `--write-subs`(manual) + `--write-auto-subs`(auto) 양쪽 모두 시도해야 하며, 우선순위는 **manual 자막 우선**이다 — manual 트랙(`ko`)이 존재하면 그것만 영속 저장하고 source 필드를 `ytdlp:manual`로 기록, manual 부재 시 auto 트랙(`ko`/`ko-orig`)으로 fallback하여 source 필드를 `ytdlp:auto`로 기록해야 한다.
- **FR-005**: 시스템은 이미 수집된 자막이 있는 영상은 디폴트 스킵하고(`--force` 플래그 시에만 덮어쓰기), 처리된/스킵된 영상 수를 표준 출력으로 보고해야 한다.
- **FR-006**: 시스템은 spec 010의 `tube-scout collect transcripts` 명령을 확장해 `--source {api|ytdlp}` 플래그를 추가해야 한다. 명시 우선순위는 (1) CLI 플래그 `--source`, (2) 환경변수 `TUBE_SCOUT_DEFAULT_TRANSCRIPT_SOURCE` (`api`/`ytdlp`), (3) 둘 다 없으면 디폴트 `api` (spec 010 backward compatibility). 운영자는 `.envrc` 또는 cron에 환경변수 한 줄 설정으로 디폴트 토글 가능.

**Audio fingerprint (P2)**:

- **FR-007**: 시스템은 자교 등록 채널의 **모든 영상**(자막 유무 무관 — FR-008 의 30s 제외 정책만 적용)에 대해 음원을 임시 추출하여 chromaprint 음향 지문을 산출하고 SQLite 테이블 `audio_fingerprint`에 영속 저장해야 한다 — spec Y(음향 매칭) 전수 입력 보장. **사전 단계**: 영상 목록은 spec 003 `tube-scout collect videos --channel <alias>` 결과 (`<project>/01_collect/videos_meta.json`) 의 video list 를 입력으로 사용 — 본 spec 은 video list 자체를 재수집하지 않는다.
- **FR-008**: 시스템은 30초 미만 영상에 대해 지문 산출을 스킵하고 audit-log에 사유 `too_short`를 기록해야 한다.
- **FR-009**: 시스템은 지문 추출 후 60초 이내에 임시 음원 파일을 삭제해야 하며, 명령 종료 시점에 임시 디렉터리 잔재가 0건이어야 한다 (정상 종료 기준).
- **FR-010**: 시스템은 이미 지문이 산출된 영상은 디폴트 스킵하고(`--force` 플래그 시에만 재산출), 처리된/스킵된 영상 수를 표준 출력으로 보고해야 한다.
- **FR-011**: 시스템은 신규 CLI 명령 `tube-scout collect audio` (음원 임시 추출, fingerprint 추출 직후 자동 삭제) 와 `tube-scout collect fingerprint` (지문 단독 — 음원 추출 + 지문 + 삭제 wrapper)를 제공해야 한다.
- **FR-011a**: 시스템은 `tube-scout collect {transcripts,audio,fingerprint}` 각 명령에 `--all-channels` 플래그를 제공해야 한다. 플래그 사용 시 spec 003 alias resolver를 통해 등록된 모든 자교 채널을 순차 처리하며, 한 채널의 실패(인증 만료/rate limit/네트워크)가 다른 채널 처리를 중단시키지 않아야 한다(FR-016과 동일 isolation). `--channel <alias>` 와 `--all-channels` 는 상호 배타이며 둘 다 누락 시 actionable 오류로 종료해야 한다.
- **FR-012**: 시스템은 spec 011의 `content_reuse.db` 스키마 v2 위에 v3 ALTER로 `audio_fingerprint` 테이블을 추가하며, 기존 컬럼·테이블 변경 0 (idempotent migration)이어야 한다.
- **FR-013**: 시스템은 지문 데이터를 base64 BLOB(`fingerprint`), 초 단위 길이(`duration REAL`), ISO8601 타임스탬프(`extracted_at`)로 저장해야 한다 (spec Y read-only 소비 시그니처 동결).

**Operational integrity (P3 + 횡단)**:

- **FR-014**: 시스템은 매 yt-dlp subprocess 호출 **직전 (before invoke)** 디폴트 `random.uniform(30.0, 60.0)`초 sleep 을 적용해야 한다. 단 채널·명령 단위 첫 호출은 sleep 0 (운영자 즉시 응답성 보존). HTTP 429 발생 시 exponential backoff (60 → 300 → 1800초, 최대 3회 재시도) 후 채널 단위 종료.
- **FR-015**: 시스템은 자막·지문 처리 결과를 `<project>/01_collect/transcripts_audit.csv` 와 `<project>/01_collect/fingerprint_audit.csv` 에 기록해야 하며, 각 행은 video_id, 결과(success/skip/fail), 사유, 타임스탬프, cookies 출처(brave/file)를 포함해야 한다.
- **FR-016**: 시스템은 인증 실패(cookies 만료/keyring locked) 시 actionable 영문 메시지(예: "Brave keyring is locked. Run `tube-scout auth refresh-cookies` …")를 출력하고 해당 채널만 종료해야 하며, 동일 cron 내 다른 채널 처리는 계속되어야 한다.
- **FR-017**: 시스템은 cookies 인증 디폴트로 `--cookies-from-browser brave`를 사용하고, 디크립션 실패 시 다음 순서로 폴백해야 한다: (1) 환경변수 `TUBE_SCOUT_COOKIES_FILE` 가 가리키는 0600 권한 파일, (2) 디폴트 경로 `~/.config/tube-scout/cookies.txt`(0600), (3) 둘 다 부재 시 actionable 영문 메시지("YouTube cookies unavailable. Install Brave extension 'Get cookies.txt LOCALLY', export youtube.com cookies, save with 0600 perms to ~/.config/tube-scout/cookies.txt or set TUBE_SCOUT_COOKIES_FILE.")와 함께 종료.
- **FR-018**: 시스템은 모든 사용자 대면 오류 메시지를 영문으로 출력하고, 다음 행동 1개를 명시(예: "Run X" / "Check Y")해야 한다 (Constitution II Fail-Fast).
- **FR-019**: 시스템은 외부 채널 차단 정책(PS-A-12)을 코드 레벨에서 보장해야 한다 — alias resolver를 거치지 않은 채널 ID/URL은 yt-dlp 호출 전에 거절되어야 한다.
- **FR-020**: 시스템은 SIGINT/SIGTERM 수신 시 임시 음원 디렉터리를 best-effort 정리하고 진행 중 영상을 audit-log에 `interrupted`로 기록한 후 종료해야 한다 (영구 보관 0 정책 보장).

### Key Entities

- **Transcript** (자막): video_id, language(ko/ko-orig), source(`ytdlp:auto` / `ytdlp:manual` / `api`), segments[{start_sec, end_sec, text}]. spec 010 형식과 동일 — 본 spec은 `source` 값만 추가.
- **Audio Temp File** (임시 음원): video_id, path, format(mp3), sample_rate(22050Hz), channels(mono). 라이프사이클: extract → fingerprint → delete (영속 0).
- **Audio Fingerprint** (음향 지문): video_id (PK), fingerprint (b64 BLOB), duration (sec, REAL), extracted_at (ISO8601). spec 011 `content_reuse.db` v3 schema에 신규 추가. spec Y(미래)가 read-only 소비.
- **Cookies Source** (인증 출처): kind ("brave" / "firefox" / "chromium" / ... / "file"), path (file 인 경우만). agenix 환경변수로 file path 주입 가능.
- **Audit Record** (처리 감사): video_id, stage(transcript/audio/fingerprint), result(success/skip/fail), reason, timestamp, cookies_source. CSV 영속, 운영자 컴플라이언스 검증용.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 운영자가 22채널 약 4,000편 강의 영상의 한국어 ASR 자막을 백필할 때 YouTube Data API quota 사용량이 0 unit이다.
- **SC-002**: 비공개(Private) 영상 약 3,544편(채널 visibility 88.6% 기준)에 대해 자막 fetch 성공률이 95% 이상이다 (실패는 본질적 자막 부재 또는 cookies 만료에 한정).
- **SC-003**: 30초 이상 영상에 대해 음향 지문이 100% 영속 저장된다 (skip 사유는 30초 미만 또는 인코딩 미지원에 한정, 두 사유는 audit CSV로 추적 가능).
- **SC-004**: 백필 명령 종료 시점에 `<project>/01_collect/audio_temp/` 디렉터리의 잔여 음원 파일은 0건이다 (Constitution V — 음원 영속 보관 금지).
- **SC-005**: 영상 1편당 백필 wall-clock 시간(자막 + 지문 합산, 평균 25분 영상 기준)이 60초 이하다 (spike 측정 자막 ~1초 + 음원 추출 12초 + 지문 1초 + sleep 30~60초). 22채널 × 4,000편 전수 백필 1회 총 시간 약 67시간 — 채널별 시차 cron으로 분산.
- **SC-006**: cookies 만료·rate limit·네트워크 실패 발생 시 운영자가 audit-log + 영문 actionable 메시지만으로 5분 이내 다음 중 하나의 **복구 조치**를 실행할 수 있다 — (1) Brave 재로그인 후 명령 재실행, (2) `chmod 600` 후 cookies.txt 재지정, (3) `--channel <alias>` 로 실패 채널만 재시도, (4) 30분 대기 후 자동 재시도. UX outcome metric — buildable test 0, 운영자 self-audit 으로 검증.
- **SC-007**: 본 spec이 산출한 transcript JSON이 spec 011 콘텐츠 재사용 분석 파이프라인(spec 010 boundary B-3)에 추가 변환 없이 100% 호환 입력으로 사용된다.
- **SC-008**: 외부 채널 video ID/URL을 인자로 전달한 모든 호출이 yt-dlp 네트워크 호출 0건으로 거절된다 (PS-A-12 코드 레벨 보장).
- **SC-009**: 운영자가 `--all-channels` 플래그로 22채널 백필 cron을 실행할 때, 임의 1개 채널의 인증·네트워크 실패가 나머지 21채널 처리를 중단시키지 않는다 (실패 채널 audit-log + 다음 채널 자동 진행).

## Assumptions

**운영 컨텍스트** (idea + spike 검증):

- 운영자는 자교 22채널의 owner 또는 위임받은 자기 백업 권한자이며, Brave 브라우저로 YouTube에 본인 인증되어 있다 (spike 922-923 cookies 디크립션 검증).
- Brave keyring이 일반적으로 unlocked 상태이며, locked 상태일 때만 cookies.txt 파일 폴백을 사용한다 (spike 검증 — production cron 환경에서는 cookies.txt 디폴트 가능).
- 운영자 머신은 NixOS이며, `flake.nix devShell` 이 yt-dlp / chromaprint / ffmpeg / zlib / stdenv.cc.cc.lib 를 LD_LIBRARY_PATH로 제공한다 (spike 검증).
- 자교 외 다른 채널은 PS-A-12에 의해 영구 scope OUT (외부 채널 모니터링은 idea/roadmap에 명시).

**기술 디폴트** (informed defaults):

- 자막 우선순위: manual `ko` > auto `ko` > auto `ko-orig` (spike에서 두 auto 트랙은 동일 ASR 결과 확인). manual 자막은 자교 채널 owner 직접 업로드분 — ASR보다 정확.
- 음원 형식: 22050Hz mono mp3 128kbps (chromaprint 권장 + ffprobe 검증 OK).
- chromaprint 지문 길이: full-length(`-length 0`). 영상 1분당 약 2 KB → 22채널 × 4,000편 × 평균 25분 ≈ 5.5 GB SQLite 단일 파일 예상.
- Rate limit 디폴트 sleep: 30~60초 random. spike에서 sleep 0으로 5분 내 6 호출 차단 0 — 30s 안전 추정. production 50+ URL 검증은 dev-squad의 `@pytest.mark.slow` integration test로 위임.
- 자막·지문 명령 디폴트는 `idempotent skip`, `--force` 플래그로만 덮어쓰기.
- 디폴트 자막 source: CLI `--source` 플래그 > 환경변수 `TUBE_SCOUT_DEFAULT_TRANSCRIPT_SOURCE` > `api` (spec 010 backward compat). v0.4 운영 단계에서는 quota 미승인 상태이므로 cron에 `TUBE_SCOUT_DEFAULT_TRANSCRIPT_SOURCE=ytdlp` 1줄 권장. quota 승인 후 환경변수 제거하면 api 디폴트로 복귀.

**버전 정책**:

- 본 spec은 v0.4.0 출시에 spec 011과 함께 포함된다 (운영자 결정 2026-05-09). pyproject.toml 기준 0.3.3 → 0.4.0 minor bump, spec X1 머지 후 git tag `v0.4.0`.

**의존성·범위**:

- 모든 cross-spec 의존성·boundary 의 권위 카탈로그는 §Cross-Spec Boundaries (B-X1-1~9) — 본 섹션은 단순 reference. 향후 변경은 §Cross-Spec Boundaries 에서만.

**범위 외**:

- 음향 매칭 알고리즘, hamming threshold tuning, 동일 강의자 baseline 측정 — spec Y(미래)
- DTW(시간축 변형) 보정 — v0.8 미래 spec
- OCR / 화자 분리 — 영구 scope OUT (`project_scope_decisions_20260506`)
- 영상 자체 영구 보관 — Constitution V 위반 (영구 0)
- 외부 채널 분석 — PS-A-12 영구 scope OUT
- 22채널 동시 다운로드 (병렬화) — 디폴트 순차. 채널별 시차 cron으로 throttle. 병렬 옵션은 본 spec scope 외.
