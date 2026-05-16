# Phase 0 Research: Takeout 통합 적재와 운영 효율화

**Branch**: `017-takeout-unified-ingest` | **Date**: 2026-05-16 | **Spec**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md)

본 문서는 spec 017 의 plan.md 작성 시점에 등장한 기술 결정을 정리한다. 각 결정은 (1) 결정한 사항, (2) 결정의 근거, (3) 검토하고 기각한 대안의 3 요소로 기록된다. spec.md 의 NEEDS CLARIFICATION 마커는 이미 사용자 결정 (Q1=C / Q2=B / Q3=Custom) 으로 해소되었으므로, 본 research 는 잔여 기술 결정에 집중한다.

---

## R-1: mp4 길이 측정의 메모이즈 방식

### Decision

`src/tube_scout/services/evidence_score.py::score_mp4_candidates` 함수의 매칭 루프 안에서, mp4 파일 1 개의 길이 정보를 함수 호출 1 회당 1 회만 외부 도구로 측정하도록 명시적 dict 캐시를 도입한다. 캐시 key 는 `mp4_path` (Path 객체) 의 절대경로 문자열이며, value 는 `_probe_duration_via_ffprobe()` 의 반환값 (`float | None`) 이다. 캐시의 lifecycle 은 단일 `score_mp4_candidates` 호출과 동일하다 (함수-local 캐시).

### Rationale

본 spec 의 SC-001 (적재 1 분 이내) 의 단일 가장 큰 효과는 ffprobe 22,986 회 → 9 회로 줄이는 데서 온다. 캐싱 범위를 함수-local 로 한정하면 (1) 캐시의 invalidation 을 고민할 필요가 없고, (2) 다른 호출자가 다른 mp4 셋을 처리할 때 캐시 누수가 없으며, (3) 단위 테스트가 단순해진다 (`functools.lru_cache` 데코레이터 대신 dict 1 개로 명시).

### Alternatives Considered

| 대안 | 평가 | 기각 사유 |
|---|---|---|
| `functools.lru_cache` 데코레이터를 `_probe_duration_via_ffprobe` 자체에 적용 | 가장 간단 | 모듈-global lifetime 이라 다른 호출자의 결과가 캐시에 남음. 단위 테스트에서 캐시 초기화가 어려움 |
| 모듈-level dict 캐시 | global 이라 누적 가능 | 캐시 invalidation 책임이 모호. 호출자가 매번 클리어해야 함 |
| mp4 path 별 SQLite 캐시 영구화 | 운영 efficiency 가 더 큼 | 본 spec 의 범위 (단일 명령 처리 시간 단축) 를 넘어가는 영구 캐시 설계는 별도 spec |
| `decide_mapping` 호출 시 mp4 duration 을 인자로 받아 함수 자체에서 ffprobe 호출 안 함 | API 변경이 큼 | spec 016 의 boundary 가 깨짐. backward compatibility 위배 |

### Implementation Sketch

```python
# evidence_score.py — score_mp4_candidates 안
def score_mp4_candidates(mp4_path, video_meta_list, *, ...):
    duration_cache: dict[str, float | None] = {}
    mp4_key = str(mp4_path.resolve())

    for vm in video_meta_list:
        if mp4_key not in duration_cache:
            duration_cache[mp4_key] = _probe_duration_via_ffprobe(mp4_path)
        dur_match = _duration_match_with_cached(
            duration_cache[mp4_key], vm.duration_seconds, 1.0
        )
        ...
```

다만 `_duration_match` 가 mp4_path 를 받아 내부적으로 ffprobe 를 호출하는 현재 구조는 변경 필요. 새 helper `_duration_match_with_cached(mp4_duration_s, video_duration_s, tol_s)` 를 도입한다.

---

## R-2: 통합 명령 (`collect ingest`) 의 흐름 orchestration 위치

### Decision

신규 모듈 `src/tube_scout/services/unified_ingest.py` 에 orchestrator 함수 `ingest_unified()` 를 신설한다. 이 함수는 spec 016 의 `ingest_takeout()` 과 spec 013 의 `process-audio` 흐름의 합집합 단계를 순차로 호출하며, 단계별 결과를 `UnifiedIngestSummary` 데이터 클래스에 집계한다. CLI 의 `collect_ingest_command` 은 본 orchestrator 의 thin wrapper 가 된다 (Constitution Principle IV).

### Rationale

- CLI 진입점에 흐름 로직을 직접 작성하면 (1) 테스트가 어려워지고 (Typer Context mocking 필요), (2) 다른 진입점 (예: 향후 web UI) 에서 재사용 불가.
- 서비스 함수로 분리하면 단위 테스트가 직접 호출 가능하며, spec 013 의 `process-audio` 와의 코드 중복을 피할 수 있다 (둘 다 `WavLifecycle` + `transcribe_audio` + `extract_chromaprint_fingerprint` 흐름).
- Constitution Principle III (Single Responsibility) — orchestrator 는 "단계 호출 + 결과 집계" 한 가지만 한다.

### Alternatives Considered

| 대안 | 평가 | 기각 사유 |
|---|---|---|
| `collect_ingest_command` 안에 흐름 로직 직접 작성 | 1 파일로 끝 | 테스트성 부재, 단일 책임 위배 |
| `services/takeout_ingest.py` 안에 통합 흐름 추가 | 기존 모듈 확장 | spec 016 의 boundary 가 모호해짐. takeout 적재가 단계 0 임을 유지하려면 별도 모듈 필요 |
| spec 013 의 `services/process_audio.py` (existing) 를 통합 진입점으로 확장 | 기존 자산 활용 | 통합 명령이 적재 단계를 포함하므로 process_audio 라는 이름이 맞지 않음. 의미 혼란 |
| 별도 패키지 `src/tube_scout/orchestrator/` 신설 | 구조 깔끔 | 1 모듈을 위한 새 패키지 도입은 over-engineering. services/ 안에 두는 게 일관 |

---

## R-3: 처리 실패 영상의 재시도 매니페스트 (retry_pending.json) 구조

### Decision

`data/<alias>/retry_pending.json` 위치에 JSON atomic write 로 저장한다. schema:

```json
{
  "schema_version": 1,
  "alias": "nursing",
  "updated_at": "2026-05-16T08:43:42+09:00",
  "entries": [
    {
      "video_id": "abc123",
      "title": "1주차 1차시",
      "failed_stage": "asr",
      "failure_reason": "model_loading_failed",
      "last_attempt_at": "2026-05-16T08:43:42+09:00",
      "attempt_count": 1
    }
  ]
}
```

다음 통합 명령 호출 시 orchestrator 가 본 매니페스트의 `entries[*].video_id` 를 SQLite 의 `processing_status` 와 join 해서 재시도 우선순위 큐로 사용한다. row 가 성공 처리되면 매니페스트에서 제거 (또는 별도 `resolved_at` 필드로 표시).

### Rationale

- 본 시스템은 외부 DB 서버를 사용하지 않으므로 (Constitution Principle V) JSON 파일이 자연스러운 선택.
- alias 별 디렉토리 (`data/<alias>/`) 에 두면 spec 016 의 boundary B-8 과 일관 (channel_meta.json, videos_meta.json 과 같은 위치).
- `schema_version` 필드를 처음부터 두어 향후 schema 진화 시 migration 흐름이 명확하게 작동.
- `attempt_count` 를 두어 무한 retry 방지 (운영자가 N 회 이상 실패하면 수동 점검 신호로 활용).

### Alternatives Considered

| 대안 | 평가 | 기각 사유 |
|---|---|---|
| SQLite `processing_status` 테이블의 새 컬럼 `retry_priority` 로 표시 | 스키마 변경 | spec 013 의 v4 스키마를 변경하면 boundary B-4 위배. ALTER COLUMN 마이그레이션 부담 |
| SQLite 신규 테이블 `retry_queue` 추가 | 일관성 | 스키마 진화는 별도 spec. 본 spec 의 PATCH/MINOR 범위 안에서는 JSON 파일이 가벼움 |
| Parquet 파일 | 분석 효율 | row 수가 적고 (실패 영상은 한 학과당 수십 건 수준) Parquet 의 컬럼 효율은 의미 없음 |
| 매니페스트 없이 SQLite query 로 매번 실패 영상 추출 | 의존성 0 | 명시적 매니페스트가 운영자에게 retry 의도를 시각화하기 좋고, 운영자가 직접 파일을 열어 점검 가능 |

---

## R-4: 영상 삭제 두 단계 prompt 의 UX 구현

### Decision

`src/tube_scout/services/source_video_cleanup.py` 에 두 함수를 분리한다.

1. `present_failure_table(failures: list[FailureEntry]) -> None` — Rich Table 으로 처리 실패 영상의 video_id, 제목, 실패 단계, 사유를 표시. 운영자에게 추가 응답을 요구하지 않음 (단순 정보 제공).
2. `confirm_and_cleanup(deletion_candidates: list[CleanupCandidate], *, prompt_io: PromptIO = ...) -> CleanupResult` — Rich Confirm prompt (`Confirm.ask("Delete N source mp4 files? (y/N)")`) 로 yes/no 받고, yes 인 경우만 unlink 수행.

`PromptIO` 는 단위 테스트에서 stdin 을 mocking 하기 위한 thin protocol. default 구현은 Rich Console.

### Rationale

- 두 함수로 분리하면 단위 테스트가 단순. `present_failure_table` 은 출력 captured snapshot 으로, `confirm_and_cleanup` 은 PromptIO mock 으로 yes/no 분기 테스트.
- spec.md FR-012 의 두 단계 흐름이 코드 상에서도 두 함수 호출로 명확히 분리.
- Rich 의 `Confirm.ask` 가 이미 Constitution Principle IV 의 "human-readable progress via Rich" 와 일관.

### Alternatives Considered

| 대안 | 평가 | 기각 사유 |
|---|---|---|
| 한 함수 `interactive_cleanup` 안에서 두 단계 모두 처리 | 호출 한 줄 | 단일 책임 위배, 테스트 어려움 |
| 표시 단계는 stdout, prompt 는 stdin 직접 read | 외부 의존성 0 | Rich 가 이미 의존성에 있고, 일관성·접근성·다국어 모두 Rich 가 더 좋음 |
| 자동 yes 옵션 (`--yes-i-really-mean-it`) 도입 | 자동화 편리 | spec.md Q3 사용자 결정 (두 단계 prompt 명시 확인) 과 충돌. 운영자의 의식적 결정을 강제하는 것이 본 spec 의 의도 |

---

## R-5: 통합 명령의 진행 표시 (Rich progress / Rich live)

### Decision

`unified_ingest()` orchestrator 는 단계별 진입 시 Rich Console 로 한 줄 헤더 (`▶ Step 1/5: Takeout 적재`) 를 출력하고, 단계 종료 시 한 줄 결과 (`✓ 적재 완료: 영상 2554, 소요 17s`) 를 출력한다. 자막·지문 단계는 영상 단위 진행률이 의미 있으므로 Rich `Progress` 컴포넌트 (TTY 인 경우만; non-TTY 환경에서는 한 줄 헤더만) 사용. 마지막에 단계별 소요 시간 + 카운트 표를 Rich Table 로 표시.

### Rationale

- 운영자가 17 분짜리 명령의 진행 상태를 보지 못하면 hang 인지 정상인지 알 수 없다 (spec 016 의 실측에서 사용자 직접 우려 표명).
- TTY 자동 감지는 spec 013 의 C-4 (TTY auto-detect progress) 정책과 일관.

### Alternatives Considered

| 대안 | 평가 | 기각 사유 |
|---|---|---|
| 진행 표시 없이 마지막 요약만 | 단순 | 운영자가 진행 상태 모름. 17 분 hang 우려 |
| stdout 에 매 영상 처리 시 한 줄 | 진행 보임 | non-TTY 환경에서 로그 폭증. Rich Progress 가 같은 일을 더 잘함 |
| 별도 진행 표시 데몬 / web dashboard | 정교 | spec 017 범위 밖. 별도 spec 으로 분리 |

---

## R-6: 적재 단계 baseline 측정 시점

### Decision

T064 (spec 016) 의 정량 SLA 측정을 spec 017 의 첫 통합 task 에서 재측정하여 새 baseline 을 박는다. 측정 대상:

1. `collect ingest --dry-run` (적재 단계만 측정, 자막+지문 skip)
2. `collect ingest` (자막+지문 포함, ASR medium 모델)
3. `collect ingest --delete-source` (영상 삭제까지 yes 응답 후)

각 3 회 평균 측정. 본 작업 머신 (RTX 3060 + 표준 PC) 기준 정량 SLA 를 plan.md 의 "Performance Goals" 와 quickstart.md 의 운영자 체크리스트에 추가한다.

### Rationale

- spec 016 의 T064 (≤ 1770 s) 는 ffprobe 비효율 17 분 기준 박힌 SLA 라 본 spec 의 효율화 후 갱신 필수.
- 측정 시점을 implementation 진입 직전 (tasks.md 의 첫 task) 으로 잡으면 baseline 이 효율화 전후 모두 명확.

---

## R-7: 버전 등급 결정 (PATCH vs MINOR)

### Decision

본 spec 의 release 시점에 pyproject.toml 의 version 을 **`0.6.0`** 으로 bump 한다 (current `0.5.1` → MINOR). 구현 진입 시점에는 `0.6.0.dev0` 으로 설정.

### Rationale

- spec 017 은 신규 명령 (`collect ingest`) 을 도입하여 운영자의 권장 호출 패턴을 변경한다. PATCH 는 기존 기능의 결함 fix 에 한정되므로 부적합.
- 기존 명령의 호출 표면은 변경하지 않으므로 (backward compat) MAJOR 는 과도.
- 사용자 메모리 `feedback_version_policy` 의 "pyproject.toml 권위, dev0 suffix → release 시점 제거" 정책 보존.

### Alternatives Considered

| 대안 | 평가 | 기각 사유 |
|---|---|---|
| PATCH (`0.5.2`) | 작은 변경처럼 보임 | 신규 명령 도입은 MINOR 수준 변화 |
| MAJOR (`1.0.0`) | 통합 흐름이 핵심 | 기존 명령 backward compat 유지하므로 MAJOR 는 과도. 1.0.0 은 별도 milestone (예: 22 학과 운영 안정성) 에 reserved |

---

## Summary

| 결정 | 위치 | 근거 |
|---|---|---|
| R-1: mp4 duration 함수-local dict 캐시 | `evidence_score.py` | SC-001 효과 + 테스트 단순성 |
| R-2: orchestrator = 신규 `services/unified_ingest.py` | `services/` | Principle III/IV + 재사용성 |
| R-3: retry_pending.json = JSON atomic write | `data/<alias>/` | Principle V + boundary B-8 |
| R-4: 영상 삭제 두 함수 분리 (present + confirm) | `services/source_video_cleanup.py` | spec.md FR-012 + 테스트 단순성 |
| R-5: Rich Console + Progress 진행 표시 | `unified_ingest()` 안 | spec 013 C-4 + 운영자 가독성 |
| R-6: 효율화 후 새 SLA baseline 측정 | tasks.md 의 첫 task | T064 갱신 + Performance Goals |
| R-7: 버전 `0.6.0` (MINOR) | release 시점 | 신규 명령 도입 = MINOR |

본 research.md 의 모든 결정은 plan.md 의 Constitution Check 와 Cross-Spec Boundaries (B-1 ~ B-10) 모두 통과한 상태에서 도출되었다. Phase 1 (data-model, contracts, quickstart) 진입 가능.
