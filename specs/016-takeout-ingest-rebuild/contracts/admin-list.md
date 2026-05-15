# CLI Contract: `tube-scout admin list`

**Spec**: [../spec.md](../spec.md) | **FR**: FR-014, FR-015 | **User Story**: US 2 (Scenario 3, 4)

## Command shape

```
tube-scout admin list
    [--json]                                     # JSON 출력 (기본은 Rich table)
```

## Inputs

| 옵션 | 타입 | 필수 | 기본값 | 의미 |
|---|---|---|---|---|
| `--json` | flag | ❌ | False | stdout 을 JSON 배열로 출력 |

## Outputs (stdout)

기본 Rich table (한국어 헤더):

```
┌────────────┬──────────────────┬─────────────────────────┬────────────┬──────────────┐
│ alias      │ display_name     │ channel_id              │ source     │ consistency  │
├────────────┼──────────────────┼─────────────────────────┼────────────┼──────────────┤
│ nursing    │ 부산보건대 간호학과 │ UCnh3tm9uQkyA260cAHfl9rg │ both       │ ok           │
│ nursing2   │ 테스트학과         │ —                       │ departments │ ok           │
└────────────┴──────────────────┴─────────────────────────┴────────────┴──────────────┘
```

`--json` 출력:

```json
[
  {
    "alias": "nursing",
    "display_name": "부산보건대 간호학과",
    "channel_id": "UCnh3tm9uQkyA260cAHfl9rg",
    "source": "both",
    "consistency": "ok"
  },
  {
    "alias": "nursing2",
    "display_name": "테스트학과",
    "channel_id": null,
    "source": "departments",
    "consistency": "ok"
  }
]
```

## Outputs (stderr)

비정합 alias 가 한 개 이상 발견되면 stderr 에 WARNING 라인 출력 (FR-015):

```
WARNING: alias 'nursing' mismatch (channels.json=UCabc, departments.json=UCdef)
```

여러 alias 가 비정합이면 한 줄씩 출력. 정상 흐름의 출력에는 영향 없음.

## Exit codes

| Code | 의미 | 트리거 |
|---|---|---|
| 0 | 성공 (정합/비정합 무관) | 조회 완료 |
| 1 | 등록부 파일 자체 손상 | channels.json 또는 departments.json 가 JSONDecodeError, 또는 스키마 validation 실패 |

비정합 alias 가 있어도 exit 0 — `admin list` 는 정보 제공 명령 (R-6). 차단은 분석 명령에서만 (collect-takeout 등).

## Source 판별 로직 (data-model.md RegistryUnionRow 참고)

```python
C = set(channels.json 의 alias)
D = set(departments.json 의 alias)
all_aliases = sorted(C ∪ D)
for alias in all_aliases:
    if alias in C and alias in D: source = "both"
    elif alias in C:              source = "channels"
    else:                          source = "departments"
```

## Consistency 판별 로직

- source == "channels" → 항상 `ok` (단일 등록부, 비교 대상 없음).
- source == "departments" → 항상 `ok` (단일 등록부).
- source == "both" → channels.json 의 `channel_id` 와 departments.json 의 `channel_id_env` 가 가리키는 환경변수 값이 일치하면 `ok`. 둘 중 하나라도 부재이거나 불일치면 `mismatch`.

## display_name 우선순위

- source == "channels": `channels.json` 의 `channel_name` 사용.
- source == "departments": `departments.json` 의 `display_name` 사용.
- source == "both": `departments.json` 의 `display_name` 우선 (운영자가 명시한 표시명).

## Cross-Spec Boundary 검증 (B-1, B-2)

- B-1: `channels.json` 의 entry 형식 (alias / channel_id / channel_name / last_used_at / token_path) 을 read-only 로 소비.
- B-2: `departments.json` 의 entry 형식 (alias / display_name / channel_id_env / client_secret_env / api_key_env / registered_at) 을 read-only 로 소비.

## 사용 흐름 (운영자 관점)

1. 신규 학과 등록 직후 `admin list` 로 확인 (US 2 Scenario 1).
2. 두 등록부의 상태 점검 (Scenario 3 — 두 다른 등록부의 alias 가 모두 보이는지).
3. 비정합 detection (Scenario 4 — `consistency=mismatch` 행 확인). `mismatch` 발견 시 운영자가 수동 해소.
