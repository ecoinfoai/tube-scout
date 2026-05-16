# Contract: `collect ingest --force` CLI 옵션

**Spec**: [../spec.md](../spec.md) | **Plan**: [../plan.md](../plan.md) | **FR**: 018D
**Surface**: `src/tube_scout/cli/collect.py::collect_ingest_command`

## 1. CLI 시그니처 (Typer)

```text
tube-scout collect ingest \
    --takeout-dir <PATH> \
    --alias <STR> \
    [--copy] \
    [--dry-run] \
    [--delete-source] \
    [--force]                # 신규 (본 PATCH)
```

### 1.1 신규 옵션

| Flag | Type | Default | Help text |
|---|---|---|---|
| `--force` | bool | False | "멱등 가드 우회 — archive 내 모든 영상의 자막·지문을 강제 재처리. retry_pending.json 은 새 결과로 갱신됨 (성공 → 제거, 실패 → 추가)." |

## 2. 동작 매트릭스

### 2.1 일반 호출 (`--force` 미지정)

| 영상 상태 | transcript skip? | fingerprint skip? | WAV 디코딩? | retry_pending 영향 |
|---|---|---|---|---|
| transcript json 없음 + DB row 없음 (fresh) | False | False | Yes (1 회) | 성공 시 entry 추가 안 함, 실패 시 추가 |
| transcript json 있음 + DB row 있음 (완료) | True | True | **No** (skip — FR-018E) | 변화 없음 |
| transcript json 있음 + DB row 없음 (지문만 미완) | True | False | Yes (지문만) | 지문 성공 시 retry entry 해소, 실패 시 갱신 |
| transcript json 없음 + DB row 있음 (자막만 미완) | False | True | Yes (자막만) | 자막 성공 시 retry entry 해소, 실패 시 갱신 |

### 2.2 `--force` 호출

| 영상 상태 | transcript 처리? | fingerprint 처리? | WAV 디코딩? | retry_pending 영향 |
|---|---|---|---|---|
| 모든 상태 (fresh / 완료 / 부분) | **Yes** | **Yes** | **Yes** (1 회) | 성공 → entry 제거, 실패 → 추가/갱신 |

`--force` 는 archive 내 영상 0 개 또는 mp4 매핑 0 개인 경우에도 옵션 자체는 valid. 처리할 대상이 없으면 자막·지문 단계의 처리/skip/실패 모두 0 으로 보고 (`SC-018-1` 의 ≤ 2 초 hot path 동일하게 적용).

## 3. Exit code 매트릭스

| 종료 상황 | Exit code | 비고 |
|---|---|---|
| 모든 단계 성공 | 0 | spec 017 의 기존 exit code 보존 |
| 자막 또는 지문 일부 실패 (`--force` 여부 무관) | 0 (warning) | spec 017 의 기존 동작 보존 — 실패는 retry_pending 으로 매니페스트화 |
| takeout 적재 단계 fatal error | spec 017 의 기존 exit code 그대로 | 본 PATCH 는 손대지 않음 |
| Typer 옵션 파싱 실패 (잘못된 --force 값 등) | 2 | Typer 표준 |
| `--alias` 미등록 | 2 | spec 016 의 fail-fast 그대로 |

## 4. Help text 검증 (contract test)

```bash
tube-scout collect ingest --help | grep -A 1 '\-\-force'
```

기대 출력에 다음이 포함:

```text
--force                  멱등 가드 우회 — archive 내 모든 영상의 자막·지문을
                         강제 재처리. retry_pending.json 은 새 결과로 갱신됨.
```

## 5. 감사 CSV (audit_writer) 영향

`stage = "ingest_orchestrator"` row 에 reason 어휘 확장:

| Reason | When | Example |
|---|---|---|
| `started` | 호출 시작 | 기존, 보존 |
| `completed` | 호출 종료 | 기존, 보존 |
| `already_transcribed` | 영상별 자막 단계 skip | **신규** (FR-018C, B-5) |
| `already_fingerprinted` | 영상별 지문 단계 skip | **신규** (FR-018C, B-5) |
| `forced_reprocess` | `--force` 호출에서 멱등 가드 우회 | **신규** (선택, FR-018D 가시성용) |

## 6. Backward compatibility

`--force` 옵션 추가 외 기존 CLI 시그니처 변경 없음. 기존 호출 스크립트 / 운영 매뉴얼 (spec 017 quickstart) 의 모든 명령 syntax 가 그대로 유효.

## 7. Acceptance scenarios (Plan B-4 / B-5)

- **AS-1**: fresh archive 에 `collect ingest --alias 간호` 호출 후 두 번째 호출 → wall clock ≤ 2 초, 단말의 Rich Table 자막·지문 행에 "skip 9 / 처리 0 / 실패 0" 표시, audit CSV 의 `already_transcribed` + `already_fingerprinted` reason 합계 = 18 (각 9 행).
- **AS-2**: AS-1 직후 `--force` 추가 호출 → wall clock 14m ± 2m, 모든 영상 재처리, `audio_fingerprint` row 수 정확히 9 (PK 단일성), retry_pending.json 에 신규 실패 0 (정상 동작 시).
- **AS-3**: archive 에 retry entry 3 개 (실패 영상) + 완료 6 개가 섞인 상태에서 일반 호출 → retry 3 만 재처리, 완료 6 은 skip, 매니페스트는 성공 시 3 해소.
- **AS-4**: AS-3 상태에서 `--force` 호출 → 9 영상 모두 재처리, 매니페스트는 신규 결과로 전체 갱신.
