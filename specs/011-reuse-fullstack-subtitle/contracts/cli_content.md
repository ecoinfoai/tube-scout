# CLI Contract: `tube-scout content` (spec 011 extensions)

**Feature**: 011-reuse-fullstack-subtitle
**Convention**: 모든 신규 명령은 spec 007의 `tube-scout content` 명령군에 추가된다. spec 007 기존 서브커맨드(`fingerprint`, `compare`, `quality`, `review`, `scan`)는 변경 없이 유지된다.

본 contract는 `/speckit.tasks` 가 생성할 contract 테스트의 ground truth다 (모든 시그니처 변경은 contract 테스트로 강제된다).

---

## 1. 변경 요약 (서브커맨드)

| 명령 | 상태 | 신규/변경 |
|---|---|---|
| `tube-scout content fingerprint` | 변경 없음 | spec 007 보존 |
| `tube-scout content compare` | **변경** | `--mode {default|nc2}` 옵션 추가 |
| `tube-scout content scan` | **변경** | `--mode {default|nc2}` + `--professor <id>` 옵션 추가 |
| `tube-scout content review` | **변경** | `--pattern <label>` 필터 + `--status PENDING` 추가 |
| `tube-scout content quality` | 변경 없음 | spec 007 보존 |
| `tube-scout content professor` | **신규** | `map`, `list`, `unmap`, `show` |
| `tube-scout content baseline` | **신규** | `bootstrap`, `add`, `list`, `remove` |
| `tube-scout content whitelist` | **신규** | `add-pair`, `add-phrase`, `list`, `export`, `remove` |
| `tube-scout content policy` | **신규** | `show`, `validate` (정책 YAML read-only 도구) |

---

## 2. `content compare` (변경)

```text
tube-scout content compare \
    --project <PATH> \
    [--mode {default|nc2}]            # default = M-default (spec 007 호환); nc2 = M-nC2
    [--professor <PROFESSOR_ID>]      # nc2 모드에서 필수, default 모드에서는 무시
    [--channel <ALIAS>]               # default 모드에서만 사용 (spec 007 인계)
```

**`compare` vs `scan` 의도 차이 (intentional duplication)**:
- `compare` — spec 007 호환 진입점. M-default가 본 명령의 1차 사용 시나리오 (spec 007 사용자가 명령을 그대로 사용). `--mode nc2`는 호환성 유지 차원에서 같은 entry point에서도 nc2 트리거 가능하게 함.
- `scan` — 파이프라인 진입점. fingerprint+compare+quality 일괄 실행 + per-pair checkpoint resume. 신규 운영자(spec 011 first-time user)는 `scan`을 권장.
- 두 명령 모두 `--mode nc2`에서 동일한 nC2 코드 경로(`nc2_matcher` + `pair_checkpoint`)에 위임하므로 결과 동일. 의도된 중복.

**유효성 규칙**:
- `--mode nc2` 인데 `--professor` 누락 → fail-fast (`Missing --professor for nC2 mode`)
- `--mode nc2` 인데 `--channel` 지정 → 경고 후 무시 (cross-channel 통합이 nC2의 핵심)
- `--mode default` (기본) 시 `--professor` 지정 → 경고 후 무시

**출력**:
- stdout: 산출 비교 쌍 수, 4 패턴별 카운트(nc2 모드), grade 분포
- exit code: 0 정상, 1 검증 실패, 2 외부 의존 누락(자막 미수집 등)

---

## 3. `content scan` (변경)

```text
tube-scout content scan \
    --project <PATH> \
    [--mode {default|nc2}] \
    [--professor <PROFESSOR_ID>] \
    [--resume]                        # 신규: 기존 pair_checkpoint에서 재개
```

`--resume` 동작 (FR-031):
- `pair_checkpoint` 테이블에서 `(professor_id, matching_mode, status='in_progress')` row 조회
- 존재 시 `comparison_results`의 미완료 쌍부터 재개
- 부재 시 새 run_id 발급 후 처음부터 시작

**진행률 표시**: rich progress bar — `[mode/professor] 1234 / 19900 pairs`.

---

## 4. `content review` (변경)

```text
tube-scout content review \
    --project <PATH> \
    [--pattern {whole-same-week|scattered-same-week|whole-different-week|scattered-different-week}]
    [--status {UNREVIEWED|PENDING|CONFIRMED_DUPLICATE|FALSE_POSITIVE}]
    [--professor <PROFESSOR_ID>]
    [--mark <PAIR_ID> {CONFIRMED_DUPLICATE|FALSE_POSITIVE|PENDING}]
```

상호작용:
- 인자 없이 호출 → rich 테이블로 미검토 쌍 목록(spec 007 동작 유지)
- `--mark` 사용 시 advisory lock 획득(`BEGIN IMMEDIATE`) 후 1회 갱신, 실패 시 영문 메시지 + exit 3
- `--pattern` 필터는 nc2 모드 산출에만 의미 (default 모드 row는 reuse_pattern=NULL이므로 빈 결과)

---

## 5. `content professor` (신규)

```text
tube-scout content professor map \
    --project <PATH> \
    --professor-id <ID> \
    --display-name <NAME> \
    --channel <ALIAS> \
    --author <AUTHOR_MARKER | __channel_owner__> \
    [--note <TEXT>]

tube-scout content professor list --project <PATH>

tube-scout content professor show --project <PATH> --professor-id <ID>

tube-scout content professor unmap --project <PATH> --professor-id <ID> --channel <ALIAS> --author <AUTHOR_MARKER>
```

**유효성**:
- `professor-id` 존재 안 하면 `map` 시점에 자동 생성, 이후 호출에서는 기존 row에 추가
- 같은 `(channel, __channel_owner__)` 매핑이 다른 professor에게 이미 등록되어 있으면 fail-fast (한 채널 = 한 교수 룰 violation)

---

## 6. `content baseline` (신규)

```text
tube-scout content baseline bootstrap \
    --project <PATH> \
    --professor <ID> \
    [--earliest-n <INT, default=5>] \
    [--min-occurrences <INT, default=3>]

tube-scout content baseline add \
    --project <PATH> \
    --professor <ID> \
    --phrase <TEXT> \
    [--source-video <VIDEO_ID>...] \
    [--reason <TEXT>]

tube-scout content baseline list --project <PATH> [--professor <ID>]

tube-scout content baseline remove --project <PATH> --professor <ID> --phrase <TEXT>
```

`bootstrap`:
- 해당 교수 풀에서 `published_at`이 가장 이른 N 영상의 자막을 normalize 후 phrase 빈도 집계
- ≥`min-occurrences` 영상에서 등장한 phrase를 `seeded=1`로 등록
- 결과: 등록된 phrase 수 + 샘플 5개 출력

`add`:
- normalize 후 동일 phrase가 이미 존재하면 `occurrences += 1` (no-op idempotent)
- 신규 phrase면 INSERT

---

## 7. `content whitelist` (신규)

```text
tube-scout content whitelist add-pair \
    --project <PATH> \
    --pair-id <COMPARISON_ID | --videos <VID_A,VID_B>> \
    --reason <TEXT>

tube-scout content whitelist add-phrase \
    --project <PATH> \
    --professor <ID> \
    --phrase <TEXT> \
    --reason <TEXT>

tube-scout content whitelist list --project <PATH> [--professor <ID>] [--type {pair|phrase}]

tube-scout content whitelist export \
    --project <PATH> \
    --format {csv|xlsx|markdown} \
    --output <PATH>

tube-scout content whitelist remove \
    --project <PATH> \
    --type {pair|phrase} \
    --id <ID>
```

`add-pair` 의미: `comparison_results.review_status = FALSE_POSITIVE`로 갱신 (spec 007 review_status 메커니즘 재사용 + Layer D가 다음 분석에서 자동 제외).

`add-phrase`: `phrase_whitelist` 테이블에 INSERT (per-professor scope).

**advisory lock**: 모든 mutation 명령은 `BEGIN IMMEDIATE`. 동시 쓰기 시 영문 메시지 + exit 3.

`export`: 사람 읽을 수 있는 포맷 (CSV/XLSX/Markdown). `phrase_raw`, `reason`, `registered_at`, `registered_by` 모두 포함 (FR-019).

---

## 8. `content policy` (신규)

```text
tube-scout content policy show --project <PATH>            # YAML 출력
tube-scout content policy validate --project <PATH>        # 누락 키, 잘못된 타입 검사
```

**Read-only**. 정책 변경은 운영자가 텍스트 에디터로 `policy.yaml` 직접 수정 (R-4 의도).

`validate` 항목:
- 모든 `composite_weights` 합계 = 1.0 (±0.01 tolerance) 인지
- `layer_c_evolution_band` 가 `[low, high]` 형식이고 0 ≤ low < high ≤ 1
- `layer_a_min_seconds > 0`
- `pattern_whole_threshold_ratio` ∈ (0, 1)

---

## 9. Common 옵션 (모든 명령)

| 옵션 | 의미 |
|---|---|
| `--project <PATH>` | 프로젝트 디렉터리 (`projects/{job-id}/...`) |
| `--verbose / -v` | 상세 로그 |
| `--dry-run` | 변경 없이 시뮬레이션 (mutation 명령에만 의미) |

---

## 10. Exit codes

| Code | 의미 |
|---|---|
| 0 | 정상 |
| 1 | 입력 검증 실패 (잘못된 옵션 조합 등) |
| 2 | 외부 의존 누락 (자막 미수집, 매핑 부재, baseline 부재) — 메시지에 actionable instruction |
| 3 | 동시 쓰기 충돌 (advisory lock 획득 실패) |
| 4 | 정책 YAML invalid |
| ≥10 | 예기치 않은 내부 오류 (스택트레이스는 stderr로) |

---

## 11. 표준 영문 에러 메시지 (Constitution Principle II)

| 상황 | 메시지 |
|---|---|
| 자막 미수집 영상 | `Captions missing for video <id>. Run 'tube-scout collect transcripts --channel <alias>' first.` |
| professor 매핑 부재 | `No professor mapping for (channel=<alias>, author=<author>). Run 'tube-scout content professor map ...' first.` |
| baseline 부재 (nc2 시) | `No baseline corpus for professor <id>. Run 'tube-scout content baseline bootstrap --professor <id>' first.` |
| 정책 YAML 누락 | `Policy file not found at <path>. Create from template: 'tube-scout content policy show > policy.yaml'.` |
| advisory lock 거부 | `Another administrator is currently writing to the review state. Please retry in a moment.` |
| nc2 모드 + 매핑된 영상 0 | `Professor <id> has no mapped videos with collected captions. Verify mapping and caption availability.` |

모든 메시지 영문, actionable instruction 포함.
