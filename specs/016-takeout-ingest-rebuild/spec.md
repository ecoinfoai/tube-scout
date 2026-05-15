# Feature Specification: Takeout 적재 모듈 재작성 및 운영자 등록 흐름 정합화

**Feature Branch**: `016-takeout-ingest-rebuild`
**Created**: 2026-05-15
**Status**: Draft
**Target version**: v0.5.1 (patch — bug fixes + Takeout pivot follow-up; no new user-facing feature). 구현 진행 중에는 `pyproject.toml` 의 version 이 `0.5.1.dev0` 으로 유지되며, master 머지 시점에 `0.5.1` 로 정리한다.
**Input**: User description: "idea/idea-spec016-takeout-ingest-defects.md idea/idea-spec016-takeout-archive-survey.md 두 개의 문서를 통해서 spec을 작성하세요."

## Context and Motivation

2026-05-12 의 결정으로 본 프로젝트는 데이터 acquisition 경로를 YouTube API/yt-dlp 에서 **Google Takeout export → 오프라인 프로세싱**으로 영구 전환하였다. 직전 spec 013(`013-takeout-local-asr-reuse`, v0.5.0) 이 Takeout 적재 코드를 처음 도입했지만 2026-05-15 실데이터 검증에서 해당 코드 모듈이 실제 Takeout 결과물의 컬럼 헤더·디렉토리 구조를 한 번도 직접 확인하지 않은 상태로 작성되었음이 드러났다. 간호학과 9개 영상 샘플(`data/takeout-20260511T130817Z-3-001/`) 로 quickstart §0.5 학과 등록 확인 → §1 Takeout 적재의 두 번째 단계 자체가 즉시 차단된다.

본 사양은 다음 두 idea 문서를 시드로 한다.

- `idea/idea-spec016-takeout-ingest-defects.md` — 어제 실데이터 검증으로 발견된 결함 1~5.
- `idea/idea-spec016-takeout-archive-survey.md` — 코드를 한 줄도 건드리지 않고 archive 안 모든 폴더/파일을 정찰한 결과. 결함 6~11 추가 및 OPEN-Q 1·2·5·6·7 정리.

핵심 결함 11 개:

| 번호 | 위치 | 핵심 |
|---|---|---|
| 결함 1 | `admin list` | 등록부가 `channels.json` 과 `departments.json` 두 곳으로 갈라져 false-negative ("등록된 학과가 없습니다") |
| 결함 2 | `admin add-department` | OAuth env 3종을 무조건 요구 — Takeout 단독 흐름과 충돌 |
| 결함 3 | `_parse_channel_csv()` | `채널 이름` 컬럼이 실제 Takeout 에 없음 (`채널 제목(원본)` 사용 필요) |
| 결함 4 | `parse_takeout_csv_metadata()` | 9개 요구 컬럼 중 6개가 실제 컬럼명과 다름, `동영상 URL` 은 컬럼 자체 없음 |
| 결함 5 | quickstart §1.2 | archive 안에서도 메타 csv 가 200영상/csv × 13파일로 분할되는 사실 미문서화 |
| 결함 6 | `_parse_channel_csv()` | `row.get("채널 이름", "")` 등이 silent fail 로 title/country 영구 None |
| 결함 7 | `parse_takeout_csv_metadata()` | privacy 가 한글(`비공개`/`일부 공개`)인데 코드는 영어만 인정 — 본 데이터 2554 영상 전부 privacy_status=None |
| 결함 8 | `meta_dir.glob("동영상*.csv")` | `동영상 녹화*.csv`, `동영상 텍스트*.csv` 까지 흡수해 컬럼 검증 단계에서 raise |
| 결함 9 | (정보 등급) | 보조 컬럼(`동영상 제목(원본) 언어` 등) 무활용 |
| 결함 10 | 두 등록부 스키마 | channels.json 은 channel_id 실제 값, departments.json 은 env 변수명만 보유 |
| 결함 11 | `add-department` 검증 | `_check_envs_present()` 의 env 강제, `--no-oauth-consent` 도 검증은 통과 못 함 |
| 결함 12 | `services/takeout_ingest.py` 의 yt_dir 결합 | 코드 가정 `takeout_dir / "YouTube 및 YouTube Music" / ...` 와 실제 archive 구조 `<takeout_dir>/Takeout/YouTube 및 YouTube Music/...` 가 한 단계 불일치. master 상태에서는 결함 3 보다 더 앞 단계 (`채널.csv not found under ... 채널`) 에서 차단된다. dev-squad Setup phase T002 baseline 실측으로 발견 (2026-05-15). |

추가 사실:

- 자교 강의 영상은 **자막이 부재**하며 향후 YouTube 자막 다운로드 계획도 없다. faster-whisper 기반 ASR 가 자막 생성의 단일 경로.
- 한 archive part 의 `동영상 메타데이터/` 폴더에는 채널 전체 2554 영상분의 메타가 모두 들어 있고, mp4 본체는 archive part 별로 분산된다 (본 archive 9개, 나머지 2545개는 다른 part).
- 부산보건대 22 학과 전체로 확장 시 메타상 영상 총수는 수만 개 예상.

## Clarifications

### Session 2026-05-15

- Q: 같은 video_id 가 다른 archive part 에서 변경된 메타(예: YouTube Studio 에서 제목/privacy 수정 후 재 export) 로 들어오면 어떻게 처리하는가? → A: `INSERT OR IGNORE` 유지 — 첫 적재 시점의 메타가 영구 진실. 후속 part 가 다른 값을 들고 와도 DB 행은 무시(audit 에도 별도 conflict 행을 남기지 않음). PATCH 범위 유지를 위해 변경 감지/덮어쓰기 정책은 본 사양 범위 밖.
- Q: 알려지지 않은 새로운 한글 privacy 값 (예: 미래의 `예약 공개`) 한 행을 만나면 어떻게 행동하는가? → A: 해당 video_id 한 행만 skip + audit 에 `result=skip, reason=unknown_privacy_value, raw_value=<원본 한글>` 기록. 같은 archive 의 다른 영상은 정상 적재 계속. 적재 전체 fail 도 sentinel `unknown` 매핑도 채택하지 않음.
- Q: `admin list` 가 두 등록부 비정합 alias 를 감지했을 때 종료 코드/출력 채널을 어떻게 처리하는가? → A: `admin list` 자체는 정보 제공 명령이므로 **exit 0 유지**. 출력에 `consistency` 컬럼 표시(`ok` / `mismatch`), `--json` 출력의 각 row 에 `"consistency"` 필드 포함, stderr 에 `WARNING: alias <X> mismatch (channels.json=<id1>, departments.json=<id2>)` 라인 추가. 비정합 alias 가 분석 명령(`collect`/`analyze`/`report`) 에 사용될 때만 명시적 오류로 차단 (FR-015 후반부). 신규 `admin verify` 명령은 PATCH 범위 밖이라 도입하지 않음.
- Q: 적재 성능 SLA 를 spec 에 정량화할 것인가, plan 단계로 deferred 할 것인가? → A: **측정·출력은 spec 의 의무**, 정량 임계 N 은 plan/tasks 단계로 위임. IngestResult 와 audit row 양쪽에 `elapsed_seconds` 필드를 기록하도록 FR-022 보강, SC-009 신설하여 측정 자체가 회귀 검증 대상임을 명시. 본 작업 머신에서 9 mp4 + 2554 메타 archive 의 적재 baseline 을 plan 단계 첫 task 에서 측정한 뒤 plan/tasks 안에 정량 임계를 박는다.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Takeout archive 적재 (Priority: P1)

학과 운영자가 `tube-scout collect takeout --takeout-dir <path> --channel <alias>` 명령으로 Takeout archive 한 묶음의 메타데이터와 mp4 본체를 시스템에 적재한다. 명령은 archive 안의 `동영상 메타데이터/` 폴더에서 채널 전체 영상 메타를 읽고, `동영상/` 폴더의 mp4 본체와 매칭하여 SQLite v4 와 channel_meta.json / videos_meta.json 에 저장한다. mp4 본체가 동봉되지 않은 영상은 메타만 적재되고 ASR/지문 단계가 자연스럽게 skip 된다.

**Why this priority**: 본 사양의 모든 다른 흐름(분석·재사용 탐지·보고서)이 이 단계의 산출물을 입력으로 한다. 현재 결함 3·4 로 인해 본 흐름이 첫 번째 명령에서 즉시 차단된 상태이며, 이를 해소하지 못하면 v0.5.0 의 모든 후속 단계가 실데이터에서 동작 불가다.

**Independent Test**: 간호학과 샘플 archive(`data/takeout-20260511T130817Z-3-001/`) 와 `nursing` alias 만으로 처음부터 끝까지 완주하여, 적재 결과가 다음 세 가지를 모두 충족하는지 확인한다. (1) SQLite `video_metadata` 테이블에 2554 행, `channel_metadata` 테이블에 1 행이 들어 있다. (2) 2554 행의 `privacy_status` 가 모두 `private`, `unlisted`, `public` 중 하나로 영어 표준값이다 (한글 그대로이거나 NULL 인 행이 0). (3) mp4 본체가 있는 9 영상에 대해 audit CSV 에 `result=success`, mp4 본체가 없는 2545 영상에 대해 `result=skip, reason=no_mp4_in_archive` 가 기록된다.

**Acceptance Scenarios**:

1. **Given** 운영자가 `nursing` alias 를 등록부에 가지고 있고 Takeout archive 한 묶음을 `data/takeout-20260511T130817Z-3-001/` 에 풀어둔 상태, **When** `tube-scout collect takeout --takeout-dir data/takeout-20260511T130817Z-3-001 --channel nursing --dry-run` 을 실행, **Then** 명령이 0 exit code 로 종료되고 `total_videos=2554, high_confidence_mappings=9, ignored_csv_count>=N` (녹화/텍스트/기타 무시 csv 수) 가 출력된다.
2. **Given** dry-run 결과를 확인 후 `--dry-run` 없이 동일 명령을 실행, **When** 적재가 완료, **Then** SQLite v4 에 채널 1행 + 영상 2554행이 들어 있고, `data/nursing/videos_meta.json` 과 `channel_meta.json` 이 atomic write 로 생성된다.
3. **Given** 같은 명령을 한 번 더 실행 (멱등성 검증), **When** 적재 완료, **Then** `new_videos=0` 이 출력되고 DB 행 수가 변하지 않으며 기존 audit CSV 의 뒤에 새 row 가 append-only 로 추가된다.
4. **Given** 영상 제목에 쉼표·줄바꿈·따옴표가 들어 있는 행이 다수 존재, **When** 적재, **Then** 어떤 행도 컬럼 시프트(쉼표가 새 컬럼으로 인식되는 현상) 없이 정확히 파싱된다.

### User Story 2 - Takeout 단독 신규 학과 등록 (Priority: P1)

학과 운영자가 `tube-scout admin add-department --alias <alias> --display <이름>` 만으로 신규 학과를 등록한다. OAuth 자격(API key / Client secret / Channel ID env) 은 모두 옵셔널이며, 명시되지 않으면 OAuth consent 단계가 자동 skip 된다. 등록이 끝나면 `tube-scout admin list` 가 새 학과를 즉시 보여준다.

**Why this priority**: Takeout 단독 운영 모델로 영구 전환했으므로 신규 학과 추가는 OAuth 없이 가능해야 한다. 현재 결함 2·11 로 인해 OAuth 환경변수 3종이 강제되어 운영자가 사용하지 않을 자격증명을 만들도록 요구된다. 또한 결함 1 로 인해 등록된 학과가 `admin list` 에서 누락되어 운영자가 "등록을 두 번 해야 한다" 는 잘못된 결론을 내리는 상태다.

**Independent Test**: `nursing2` 라는 가짜 alias 를 OAuth env 명시 없이 등록하고, `admin list` 가 기존 `nursing` 과 신규 `nursing2` 두 학과를 모두 표시하는지 확인. 등록부 파일도 atomic write 로 누락 없이 저장되었는지 확인.

**Acceptance Scenarios**:

1. **Given** 환경변수 `TUBE_SCOUT_*` 이 하나도 설정되지 않은 상태, **When** `tube-scout admin add-department --alias nursing2 --display "테스트학과"` 실행, **Then** 명령이 0 exit code 로 종료되고 `departments.json` 에 새 행이 atomic 으로 추가된다. (OAuth consent 단계는 자동 skip)
2. **Given** 같은 운영자가 추가로 `tube-scout admin add-department --alias nursing3 --display "테스트학과2" --channel-id-env TUBE_SCOUT_CH_ID_NURSING3 --client-secret-env TUBE_SCOUT_OAUTH_CLIENT --api-key-env TUBE_SCOUT_API_KEY` 를 실행, **When** 세 env 가 모두 정의되어 있는 상태, **Then** 기존 OAuth 흐름(spec 003) 이 그대로 작동하여 token 이 발급된다 (호환성 유지).
3. **Given** `channels.json` 에는 `nursing` 만, `departments.json` 에는 `nursing2` 만 등록된 상태, **When** `tube-scout admin list` 실행, **Then** 출력에 두 alias 가 모두 표시되고 각 alias 의 source(`channels.json` / `departments.json` / `both`) 가 명시된다.
4. **Given** 한 alias 가 양쪽 등록부에 다른 channel_id 로 들어 있는 비정합 상태, **When** `admin list` 실행, **Then** 비정합 경고가 출력되며 그 alias 가 분석 명령에서 사용될 때 명시적 오류로 차단된다.

### User Story 3 - 다중 archive part 누적 적재 (Priority: P2)

운영자가 한 학과의 여러 archive part(`takeout-...-3-001`, `-3-002`, ...) 를 순서대로 풀어서 같은 alias 에 적재한다. 각 part 적재 후 새로 발견된 mp4 본체에 대해 ASR/지문 단계가 실행되고, 이미 처리된 영상은 다시 처리되지 않는다.

**Why this priority**: 자교 한 학과의 mp4 총량이 약 2.4 TB 라서 모든 part 를 한 번에 풀 수 없고 시간차로 누적 적재가 일반적 운영 시나리오다. 데이터 사이즈와 운영 자원의 제약상 P1 다음으로 중요하지만, P1 의 멱등성 요건이 충족되면 본 P2 는 자연스럽게 따라온다.

**Independent Test**: 같은 archive 를 두 번 풀어 두 다른 디렉토리에 두고 두 번 `collect takeout` 을 실행. 두 번째 실행에서 `new_videos=0` 이 나오고 SQLite 행 수가 늘지 않아야 한다.

**Acceptance Scenarios**:

1. **Given** part 1 적재 완료 후 part 2 가 풀린 상태, **When** `collect takeout --takeout-dir <part2> --channel nursing` 실행, **Then** part 2 에서 새로 발견된 mp4 에 대해서만 mp4 symlink/copy 가 만들어지고 audit 에 추가된다.
2. **Given** part 1 에 동봉된 메타 csv 와 part 2 에 동봉된 메타 csv 가 동일 (사용자 미확인 — OPEN-Q-1 의 대응으로 멱등성으로 안전 처리), **When** part 2 적재, **Then** 같은 video_id 에 대해 DB 의 `INSERT OR IGNORE` 가 작동해 행 중복 없음.
3. **Given** part 2 의 메타에 part 1 메타에 없던 영상이 추가되어 있는 경우(예: 새로 업로드된 영상), **When** part 2 적재, **Then** 새 video_id 가 DB 에 추가되고 `new_videos` 카운트에 반영된다.

### User Story 4 - 자막 부재 영상의 ASR 단일 경로 (Priority: P2)

자교 강의 영상은 Takeout 에 자막이 동봉되지 않고 YouTube 자체 자막도 없으므로, 자막이 필요한 모든 영상은 faster-whisper ASR 로 새로 생성된다. spec 013 의 `--source asr` 가 기본·유일 경로가 되고, `--source youtube` 같은 분기는 deprecate 된다.

**Why this priority**: 본 분기 단순화는 적재 결함을 해소한 뒤에도 사용자 체감 혼란 (어떤 source 를 골라야 하는지) 을 줄인다. P1 차단 해소가 먼저이므로 P2.

**Independent Test**: `tube-scout collect transcripts --channel nursing` 을 source 옵션 없이 실행했을 때 ASR 단일 경로로 동작하는지 확인. `--source youtube` 사용 시 명확한 deprecation 경고가 출력되는지 확인.

**Acceptance Scenarios**:

1. **Given** mp4 본체 9개가 `data/nursing/동영상/` 에 symlink 되어 있는 상태, **When** `tube-scout collect transcripts --channel nursing` 실행, **Then** 9개 mp4 에 대해 faster-whisper ASR 가 실행되어 자막 텍스트가 생성된다.
2. **Given** 같은 명령에 `--source youtube` 를 명시, **When** 실행, **Then** "YouTube 자막 source 는 2026-05-12 결정으로 폐기되었습니다. --source asr 가 기본값입니다" 메시지와 함께 종료 코드 2 로 중단된다.

### Edge Cases

- 한 archive 안에 영상 메타 csv 가 0 개 (적재 실패 또는 빈 archive) — 명확한 오류 메시지로 즉시 종료.
- `채널.csv` 에 데이터 행이 0 개 — 같은 처리.
- mp4 파일명이 메타의 영상 제목과 정확히 일치하지 않는 경우 — evidence-score fuzzy 매핑으로 medium/ambiguous/unmapped 결정, audit 에 confidence 기록.
- mp4 파일명에 공백·괄호·온점·한글이 섞인 경우 — `subprocess.run(cmd, ...)` 의 list-argv 방식으로 안전 처리(이미 코드에서 보장되어 있음).
- privacy 값이 본 검증 데이터에는 없는 `공개` 인 경우 — `public` 으로 매핑.
- privacy 값이 미래에 새로운 한글 값으로 바뀐 경우(예: `예약 공개`) — 해당 video_id row 만 skip + audit `reason=unknown_privacy_value, raw_value=<원본 한글>` 기록. 다른 영상의 적재는 계속 진행 (FR-005 참조).
- 두 등록부의 같은 alias 가 다른 channel_id 를 가리키는 경우 — `admin list` 가 경고 표시, 분석 명령에서는 명시적 오류로 차단.
- `동영상 메타데이터/` 폴더 안에 미래에 새로운 csv 시리즈(예: `동영상 댓글*.csv`) 가 추가되는 경우 — 정확 glob 패턴이 `동영상.csv` 와 `동영상(N).csv` 만 잡으므로 새 시리즈는 자동 무시되고 audit 의 `ignored_csv_count` 에 카운트된다.
- 같은 archive 를 두 번 적재 (운영자 실수) — 멱등으로 처리 (`new_videos=0`).
- `--takeout-dir` 가 archive root (`Takeout/` 부모) 인 경우와 `Takeout/` 폴더 자체인 경우 둘 다 동일하게 적재 성공 (결함 12 회귀 — yt_dir 자동 탐색 로직, FR-001 후반부).

## Cross-Spec Boundaries *(mandatory per Constitution VII)*

본 사양은 단독 신규 기능이 아니라 spec 003 / 008 / 013 의 결합부에서 발견된 결함 11 개를 수정하는 PATCH 다. 따라서 prior spec 들의 경계 가정과 본 사양이 보존·변경하는 부분을 다음 8 개 boundary 표로 명시한다.

| # | Prior spec / 외부 시스템 | 공유하는 것 | Prior 측 보장 | 본 spec 의 가정 / 새로 생산하는 것 | 경계 검증 |
|---|---|---|---|---|---|
| B-1 | spec 003 (multichannel-admin) | `~/.config/tube-scout/tokens/channels.json` registry | alias → channel_id + channel_name + last_used_at + token_path 의 일관된 entry | 본 spec 은 channel_id 와 channel_name 을 read-only 로 소비, 또한 `admin list` union 출력 시 source=channels 로 식별. 새로 admin list 의 비정합 경고 + alias 검증 추가. | US 2 Scenario 3 (admin list union 출력에서 nursing 가 source=channels 로 표시) |
| B-2 | spec 008 (admin-web-ui) | `${CONFIG_DIR}/departments.json` registry | alias → display_name + (channel_id_env, client_secret_env, api_key_env) + registered_at, atomic write 보장 | 본 spec 은 OAuth env 3 필드를 nullable 로 받고, Takeout 단독 등록 시 모두 None 으로 저장. 새로 `admin list` 가 source=departments 로 식별 + union 비정합 검증. | US 2 Scenario 1 (TUBE_SCOUT_* 환경변수 없이 add-department 성공 + departments.json 에 OAuth 3 필드 null 로 atomic 저장) |
| B-3 | spec 013 (takeout-local-asr-reuse) | `services/takeout_ingest.py` 의 함수 시그니처 `ingest_takeout(takeout_dir, channel_alias, db_path, work_root, *, use_symlinks, dry_run) → IngestResult` | dry_run / use_symlinks 옵션, IngestResult 카운트 필드 8 개 | 본 spec 은 함수 시그니처를 보존하면서 내부 파싱 로직 재작성 + IngestResult 에 `elapsed_seconds`, `mp4_present_count`, `mp4_absent_count` 3 개 필드 추가. **신규 3 필드는 Pydantic 기본값(`= 0`, `= 0.0`) 으로 backward-compatible** — 기존 caller (예: spec 008 web UI 의 admin job runner) 가 새 필드를 enumerate 하지 않아도 정상 작동. | US 1 Scenario 1~3 (dry-run / 실적재 / 멱등성 회귀 모두 같은 시그니처) |
| B-4 | spec 013 | SQLite v4 schema: `channel_metadata`, `video_metadata`, `processing_status`, `quality_results`, `comparison_results` | spec 013 의 migration 흐름 (v3 → v4) 과 INSERT OR IGNORE 멱등 보장 | 본 spec 은 schema 변경 없음 (v4 유지). `video_metadata.privacy_status` 컬럼에 영어 표준값만 들어가고, 알 수 없는 한글 값은 row 자체가 skip 되어 NULL 도 들어가지 않는다. | SC-002 (privacy_status 가 영어 표준값인 행 = 적재된 전체 행) |
| B-5 | spec 013 | audit CSV 형식 (stage `takeout_ingest`) | `audit_writer.py` 의 append-only 컬럼 셋: `stage`, `video_id`, `result`, `reason`, `mp4_filename`, `match_confidence`, `score`, `timestamp` | 본 spec 은 reason 어휘에 `no_mp4_in_archive`, `unknown_privacy_value`, `ignored_by_policy` 추가. `elapsed_ms` 컬럼 신설 (FR-023). audit_writer.py 함수 시그니처는 보존. | US 1 Scenario "9 success + 2545 skip(no_mp4_in_archive)" 분포 검증 |
| B-6 | spec 013 | `--source asr` / `--source youtube` source 옵션 | spec 013 의 `collect transcripts` 가 두 source 분기를 인식 | 본 spec 은 `--source youtube` 만 deprecated (exit 2 + 명확 메시지). `--source asr` 가 기본·유일 경로. CLI 시그니처는 보존하되 source enum 의 의미를 단순화. | US 4 Scenario 1~2 (옵션 없이 ASR / `--source youtube` deprecation 차단) |
| B-7 | spec 013 + agenix (외부 시스템) | `TUBE_SCOUT_*` agenix 환경변수 (channel_id / client_secret / api_key) | spec 003 OAuth 흐름에서 명시 시 검증 후 token 발급 | 본 spec 은 환경변수 자체에 새로운 의미를 부여하지 않음. add-department 단계에서 모두 명시되면 spec 003 OAuth 흐름이 그대로 작동 (호환), 모두 생략되면 OAuth consent 단계 skip (Takeout 단독). 일부만 명시되면 명시적 오류 (FR-013). | US 2 Scenario 2 (3 env 모두 명시 시 OAuth 토큰 발급, US 2 Scenario 1 의 대비) |
| B-8 | spec 003 + spec 013 (디렉토리 컨벤션) | `data/{alias}/` work root 디렉토리 — `동영상/` 폴더, `videos_meta.json`, `channel_meta.json`, audit CSV | spec 013 가 atomic write + symlink 정책 정의 | 본 spec 은 디렉토리 구조와 atomic write 규약을 보존. mp4 부재 영상은 `동영상/` 폴더에 symlink 가 생성되지 않으며 audit row 로만 추적. | US 3 Scenario 1 (part 2 적재 시 새 mp4 만 symlink 추가 + 기존 part 1 의 symlink 유지) |

위 8 개 boundary 중 B-4 의 schema 보존이 깨지면 spec 011/013 의 nC2 매칭 코드가 모두 영향. B-3, B-5 의 함수/audit 시그니처 보존이 깨지면 spec 013 Phase 5 의 audit_writer 일반화가 영향. 따라서 본 spec 의 모든 코드 수정은 위 보장된 시그니처/스키마를 보존하면서 내부 파싱·매핑·검증만 재작성하는 형태로 진행한다.

## Requirements *(mandatory)*

### Functional Requirements — 적재 모듈 재작성 (P1)

- **FR-001**: 시스템은 한국어 Takeout export 의 `채널.csv` 를 실측 헤더 `채널 ID, 채널 국가, 채널 태그 1, 채널 제목(원본), 채널 공개 상태` 로 파싱해야 한다. 채널명은 `채널 제목(원본)`, 국가는 `채널 국가` 컬럼에서 읽는다. **`--takeout-dir` 인자는 archive root (`Takeout/` 폴더의 부모) 와 `Takeout/` 폴더 자체 둘 다 허용한다** — 코드는 `takeout_dir/Takeout/YouTube 및 YouTube Music/` 가 존재하면 그 경로를, 아니면 `takeout_dir/YouTube 및 YouTube Music/` 를 시도, 둘 다 부재 시 명시적 `FileNotFoundError` (결함 12, FR-006 와 일관).
- **FR-002**: 시스템은 `동영상.csv` 와 `동영상(N).csv` 만 영상 메타로 인식해야 하며, 같은 폴더의 `동영상 녹화*.csv`, `동영상 텍스트*.csv` 등 다른 시리즈는 컬럼 검증 단계에서 raise 하지 않고 ignored audit 으로 기록해야 한다.
- **FR-003**: 시스템은 영상 메타 csv 의 실측 헤더 11 컬럼(`동영상 ID`, `근사치 길이(밀리초)`, `동영상 오디오 언어`, `동영상 카테고리`, `동영상 설명(원본) 언어`, `채널 ID`, `동영상 제목(원본)`, `동영상 제목(원본) 언어`, `개인 정보 보호`, `동영상 상태`, `동영상 생성 타임스탬프`) 을 인식해야 한다. `동영상 URL` 컬럼이 존재하지 않는 사실을 코드 가정에 반영한다.
- **FR-004**: 시스템은 영상 URL 이 필요한 경우 video_id 로부터 `https://youtu.be/<video_id>` 규칙으로 직접 도출해야 한다. 메타 컬럼에서 URL 을 읽으려 시도하지 않는다.
- **FR-005**: 시스템은 한글 privacy 값 (`공개`, `일부 공개`, `비공개`) 을 표준 영어 값 (`public`, `unlisted`, `private`) 으로 매핑한 뒤 DB 에 저장해야 한다. 매핑 표에 없는 새로운 값이 등장한 row 는 **해당 row 만 skip** 하고 audit CSV 에 `result=skip, reason=unknown_privacy_value, raw_value=<원본 한글>` 을 명시적으로 기록한다. 적재 전체 fail 도 NULL 로의 silent fail 도 금지된다.
- **FR-006**: 시스템은 `채널 제목(원본)` 과 `채널 국가` 컬럼이 채널.csv 에 부재하면 명시적 오류로 즉시 실패해야 한다. silent fail (None 으로 저장) 은 금지된다.
- **FR-007**: 시스템은 한 archive part 의 `동영상 메타데이터/` 폴더에서 채널 전체 영상 메타(본 검증 환경 기준 2554 영상) 를 모두 읽고 dedup 한 뒤 DB 에 적재해야 한다. 메타 적재는 mp4 본체 존재 여부와 독립이다.
- **FR-008**: 시스템은 mp4 본체가 동봉되지 않은 영상에 대해 ASR/지문 단계를 skip 하고, audit CSV 에 `result=skip, reason=no_mp4_in_archive` 를 기록해야 한다.
- **FR-009**: 시스템은 같은 archive 또는 다른 part 의 같은 video_id 를 두 번째로 적재할 때 DB 에 중복 행을 만들지 않아야 한다 (`INSERT OR IGNORE` 또는 동등 멱등 보장). audit CSV 는 append-only 로 누적된다. **첫 적재 우선 (first-write-wins) 정책 유지**: 후속 part 의 메타가 기존 행과 값이 달라도 DB 행은 변경하지 않으며 별도의 conflict audit 행을 남기지 않는다 (변경 감지/덮어쓰기 정책은 본 사양 범위 밖).
- **FR-010**: 시스템은 모든 csv 파싱에서 RFC4180 quoting-safe 파서(Python `csv` 모듈) 를 사용해야 한다. 영상 제목에 쉼표·줄바꿈·따옴표가 포함된 행도 컬럼 시프트 없이 정확히 파싱되어야 한다.
- **FR-011**: 시스템은 `_IGNORED_PATTERNS` 정책 (녹화/텍스트/댓글/재생목록/구독정보/시청 기록/검색 기록 무시) 을 유지하되, 적용 시점이 메타 디렉토리 내부 파일 단위까지 확장되도록 한다. 즉 결함 8 의 glob 광범위 흡수 문제와 본 무시 정책이 함께 작동해야 한다.

### Functional Requirements — 운영자 등록 흐름 (P1)

- **FR-012**: 시스템의 `tube-scout admin add-department` 명령은 `--channel-id-env`, `--client-secret-env`, `--api-key-env` 옵션을 모두 optional 로 받아야 한다. 세 옵션이 모두 명시되지 않으면 OAuth consent 단계 자체가 자동 skip 된다.
- **FR-013**: 시스템의 `add-department` 가 세 OAuth env 옵션이 일부만 명시된 경우(예: 둘만 명시) 명확한 검증 오류로 종료해야 한다 (Takeout-only 의도면 모두 생략, with-OAuth 의도면 모두 명시).
- **FR-014**: 시스템의 `tube-scout admin list` 명령은 `channels.json` 과 `departments.json` 두 등록부의 union 을 출력해야 한다. 출력의 각 행은 어느 등록부에서 왔는지 명시(`source=channels` / `source=departments` / `source=both`)한다. 명령 자체는 정보 제공이므로 비정합 행 존재 여부와 무관하게 **exit 0** 으로 종료한다.
- **FR-015**: 시스템은 두 등록부에 동시 등록된 alias 의 `channel_id` 값이 일치하지 않으면 `admin list` 의 각 행에 `consistency` 컬럼(`ok` / `mismatch`) 을 표시하고, `--json` 출력에서는 row 별 `"consistency"` 필드로 동일 정보를 노출하며, stderr 에 `WARNING: alias <X> mismatch (channels.json=<id1>, departments.json=<id2>)` 라인을 출력해야 한다. 비정합 alias 가 분석 명령(`collect`, `analyze`, `report`) 에 사용될 때는 명시적 오류 (exit 비제로) 로 차단된다.
- **FR-016**: 시스템의 `add-department` 는 신규 등록 후 같은 alias 가 다른 등록부에 이미 존재하면 (다른 channel_id 또는 다른 display_name 으로) `DuplicateAliasError` 와 동등한 명확한 실패로 종료해야 한다.

### Functional Requirements — 자막 단일 경로 (P2)

- **FR-017**: 시스템의 자막 생성 경로는 faster-whisper 기반 ASR (`--source asr`) 가 기본·유일 경로가 된다. `tube-scout collect transcripts --channel <alias>` 의 source 옵션이 생략되면 ASR 가 자동 선택된다.
- **FR-018**: 시스템은 `--source youtube` 가 명시된 경우 명확한 deprecation 메시지와 함께 종료 코드 2 로 실행을 차단해야 한다 (2026-05-12 폐기 결정 명시).
- **FR-019**: 시스템은 자막 생성 시 mp4 본체가 동봉되지 않은 영상을 자동으로 skip 하고 audit 에 `reason=no_mp4_in_archive` 로 기록해야 한다 (FR-008 과 일관).

### Functional Requirements — 분할 part 누적 (P2)

- **FR-020**: 시스템은 한 alias 에 대해 여러 archive part 를 순차 적재하는 시나리오를 지원해야 한다. 각 part 의 메타 csv 는 멱등으로 dedup 되고, mp4 본체는 새로 발견된 것만 새 symlink/copy 가 생성된다.
- **FR-021**: 시스템은 한 archive part 안에서 `동영상.csv` 와 `동영상(1)~(N).csv` 가 200 영상/csv 단위로 분할된다는 사실을 quickstart 문서에 명시해야 한다. 코드는 정확 glob 패턴(`동영상.csv` + `동영상(*).csv`) 으로 분할 파일을 모두 수집한다.

### Functional Requirements — 운영자 관측성 (P2)

- **FR-022**: 시스템은 각 적재 실행 후 IngestResult 에 다음 카운트와 측정값을 모두 출력해야 한다 — `total_videos`, `new_videos`, `high/medium/ambiguous/unmapped_mappings`, `ignored_csv_count`, `mp4_present_count`, `mp4_absent_count`, `elapsed_seconds` (적재 실행에 소요된 wall-clock 시간). 이를 통해 운영자가 archive 한 묶음의 효과와 적재 소요 시간을 즉시 파악한다. 정량 SLA 임계값(N분 이내) 은 본 사양 범위 밖이며 plan/tasks 단계에서 baseline 측정 후 결정한다.
- **FR-023**: 시스템은 audit CSV 의 각 row 에 `result`(success/skip/failure), `reason`(no_mp4_in_archive/ignored_by_policy/unknown_privacy_value/...), `match_confidence`, `score`, `timestamp`, `elapsed_ms` (해당 row 처리 소요 시간) 를 일관 형식으로 기록해야 한다. silent skip 은 금지된다.

### Key Entities *(include if feature involves data)*

- **TakeoutArchive**: Google Takeout export 한 묶음. 디렉토리 구조 `Takeout/YouTube 및 YouTube Music/{동영상,동영상 메타데이터,채널,...}` 을 가진다. 한 묶음 안에 채널 전체 메타와 mp4 본체 일부가 들어 있다.
- **ChannelMetadata**: 채널.csv 에서 파싱된 채널 메타데이터. 필드 = `channel_id`, `channel_alias` (사용자 입력), `title` (=`채널 제목(원본)`), `country` (=`채널 국가`), `privacy_status` (한글 → 영어 매핑된 값), `source="takeout"`, `ingested_at`.
- **VideoMetadata**: 동영상*.csv 에서 파싱된 영상 메타데이터. 필드 = `video_id`, `channel_id`, `title` (=`동영상 제목(원본)`), `duration_seconds` (=`근사치 길이(밀리초)`/1000), `language` (=`동영상 오디오 언어`), `category` (=`동영상 카테고리`), `privacy_status` (한글 → 영어 매핑), `created_at`, `source="takeout"`, `match_confidence`, `mp4_relative_path`, `ingested_at`.
- **IngestAuditEntry**: 적재 audit CSV 의 한 행. 필드 = `video_id`, `result`, `reason`, `mp4_filename`, `match_confidence`, `score`, `timestamp`.
- **ChannelRegistration**: 기존 `channels.json` 의 한 entry. spec 003 로부터 유지. 필드 = `alias`, `channel_id`, `channel_name`, `registered_at`, `last_used_at`, `token_path`.
- **Department**: 기존 `departments.json` 의 한 entry. spec 008 로부터 유지. 필드 = `alias`, `display_name`, `channel_id_env`, `client_secret_env`, `api_key_env`, `registered_at`. spec 016 이후 OAuth env 3 필드는 모두 nullable.
- **RegistryUnionRow**: `admin list` 가 출력하는 행. 필드 = `alias`, `display_name`, `channel_id`, `source` (channels/departments/both), `consistency` (ok/mismatch). `consistency=mismatch` 인 행은 `admin list` 의 exit code 에는 영향을 주지 않지만 stderr 의 WARNING 라인과 `--json` 출력의 `consistency` 필드로 외부 자동화가 감지할 수 있다.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 간호학과 9개 영상 archive(`takeout-20260511T130817Z-3-001`) 에 대해 `tube-scout collect takeout --channel nursing` 명령이 처음부터 끝까지 0 exit code 로 완주한다. 현재 상태에서는 결함 3·4 로 인해 첫 1초 안에 차단된다.
- **SC-002**: 같은 archive 적재 후 SQLite v4 의 `video_metadata` 테이블에 2554 행이 들어가 있고, 그중 `privacy_status` 가 `private`/`unlisted`/`public` 영어 표준값인 행이 2554 행이다 (한글 그대로이거나 NULL 인 행이 0 행). 현재 상태에서는 NULL 행이 2554/2554 (100%).
- **SC-003**: 운영자가 OAuth 환경변수를 하나도 정의하지 않은 상태에서 `tube-scout admin add-department --alias <new> --display <이름>` 만으로 신규 학과 등록을 완료할 수 있다. 현재 상태에서는 종료 코드 1 로 실패한다.
- **SC-004**: `tube-scout admin list` 가 `channels.json` 등록 학과와 `departments.json` 등록 학과를 모두 표시한다 (출력 학과 수 ≥ max(`channels.json` 행 수, `departments.json` 행 수)). 현재 상태에서는 한쪽 등록부에 있는 학과가 "등록된 학과가 없습니다" 로 표시되는 false-negative 가 일어난다.
- **SC-005**: 같은 archive 를 두 번 연속 적재했을 때 두 번째 실행의 `new_videos=0`, `mp4_added=0` 이며 SQLite 행 수가 변하지 않는다 (멱등성). audit CSV 는 두 실행분이 모두 누적되어 append-only 로 행 수가 증가한다.
- **SC-006**: `tube-scout collect transcripts --channel nursing` 을 source 옵션 없이 실행했을 때 faster-whisper ASR 단일 경로로 9개 mp4 의 자막이 생성된다. `--source youtube` 명시 시 종료 코드 2 로 명확한 deprecation 메시지가 출력된다.
- **SC-007**: 영상 제목에 쉼표·줄바꿈·따옴표가 들어 있는 행이 100 행 이상 포함된 archive 에 대해 적재가 완료된 후, 임의 표본 20 행의 DB `title` 필드 값이 원본 csv 의 `동영상 제목(원본)` 값과 글자 단위로 정확히 일치한다.
- **SC-008**: 결함 1·2·3·4·6·7·8·11 의 8 개 결함 모두에 대해 회귀 테스트(failing test → passing test) 가 작성되어 spec 016 종료 시점에 CI 에서 녹색이다. 결함 5·9·10 의 3 개는 문서/구조 변경만 동반하므로 회귀 테스트 대상 외다.
- **SC-009**: 모든 적재 실행에서 IngestResult 의 `elapsed_seconds` 와 audit row 의 `elapsed_ms` 가 0 또는 NULL 이 아닌 양의 값으로 기록된다. 정량 임계값(N분 이내) 은 plan/tasks 단계의 baseline 측정 후 별도 검증 기준으로 추가된다 — spec 016 본 단계의 회귀 검증은 측정·기록 자체의 존재 여부에 한정한다.

## Assumptions

- **한국어 Takeout export 단일 지원**. 영어 export (`YouTube and YouTube Music/Videos/...`) 의 폴더·컬럼 이름 매핑은 본 사양 범위 밖이며 미래 spec 에서 다룬다. 부산보건대 22 학과 운영자가 모두 한국어 Google 계정을 사용한다는 사용자 확인에 근거.
- **`동영상 텍스트(N).csv` 의 OCR 텍스트 활용 제외**. 자막이 아니라 영상 제목 OCR 추정 텍스트 + 타임스탬프. 본 사양에서는 무시 정책 유지, 분석 활용은 추후 separate spec.
- **두 등록부 공존 + union 표시**. `channels.json` 단일화 마이그레이션은 본 사양 범위 밖. 변경 최소화 원칙(spec 008 웹 UI 보존) 에 따라 공존 + alias 일관성 검증 FR-014~015 로 결함 1 의 false-negative 만 해소한다.
- **다중 archive part 의 메타 동봉 위치는 "모든 part 에 메타 중복 동봉" 가정**. 본 사양 작성 시점에 단 한 part(3-001) 만 검증 가능했고 사용자도 미확인. 멱등 적재(FR-009) 로 잘못 가정해도 안전. 사용자가 다음 archive part 를 풀어 메타 폴더 부재가 확인되면 FR-021 의 quickstart 문서를 보강한다.
- **자막은 모든 영상에서 ASR 단일 경로**. YouTube 자막 다운로드 흐름(`--source youtube`) 은 deprecate 되며 향후 자막 다운로드 계획은 없다 (2026-05-15 사용자 확정).
- **mp4 부재 영상에 대한 ASR/지문 skip 정책**. 한 archive part 의 메타에는 채널 전체 영상이 들어가지만 mp4 본체는 part 별로 분산된다. 본 사양은 mp4 부재를 정상 흐름의 일부로 다룬다 (FR-008, FR-019, audit `no_mp4_in_archive`).
- **검증 환경**: NVIDIA RTX 3060 (6GB) + CTranslate2 4.7.1 + faster-whisper 1.2.1 정상 작동 확인. medium 크기까지의 ASR 모델 안전. large-v3 는 별도 GPU 서버 단계로 분리.
- **분석 GPU 서버 분리**: 본 작업 머신은 검증·개발 용도. 22 학과 × 수만 영상의 본격 분석은 별도 GPU 서버에서 수행. 본 사양의 검증 시나리오는 9개 샘플 → 채널 전체 2554 영상 메타 + 9 mp4 로 한정.
- **에러 메시지 언어 분리 정책**: CLI 의 user-facing 출력(stdout 의 Rich table, stderr 의 ERROR/WARNING 라인 — 운영자가 화면에서 직접 읽는 layer) 은 운영자(한국어 화자) 가독성을 위해 **한국어** 유지. 내부 Python `raise ValueError(...)` 같은 exception message, log string, assertion message 는 **English** (Constitution II 의 "user-facing localization is the responsibility of the UI layer, not core code" 조항 + CLAUDE.md §2.2 의 "Error messages, log strings, assertion messages" 의 English 의무). 본 분리 정책은 spec 003/008/013 등 기존 spec 의 관행과 일치.

## Dependencies

- **spec 003 (`003-multichannel-admin`)** — `channels.json` 등록부, `tube-scout admin` 명령 그룹. 본 사양은 admin 흐름을 결함 1·2·11 에 한해 수정.
- **spec 008 (`008-admin-web-ui`)** — `departments.json` 등록부, `DepartmentsRepo`. 본 사양은 공존을 유지하며 `admin list` 의 union 출력으로 결함 1 해소.
- **spec 013 (`013-takeout-local-asr-reuse`)** — `services/takeout_ingest.py`, `services/asr.py`, `services/audio_extract.py`, SQLite v4 스키마, audit CSV 구조. 본 사양은 `takeout_ingest.py` 를 사실상 재작성하고 spec 013 의 ASR 흐름을 자막 단일 경로로 단순화한다.
- **외부 도구**: faster-whisper >= 1.0.0, CTranslate2 4.x, ffmpeg (chromaprint 패키지에 동봉). agenix 환경변수는 OAuth 흐름에서만 선택적 사용.
