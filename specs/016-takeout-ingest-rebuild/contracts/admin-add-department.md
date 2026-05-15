# CLI Contract: `tube-scout admin add-department`

**Spec**: [../spec.md](../spec.md) | **FR**: FR-012, FR-013, FR-016 | **User Story**: US 2

## Command shape

```
tube-scout admin add-department
    --alias <alias>                              # required
    --display <name>                             # required (1~32자)
    [--channel-id-env <ENV_NAME>]                # spec 016: required → optional
    [--client-secret-env <ENV_NAME>]             # spec 016: required → optional
    [--api-key-env <ENV_NAME>]                   # spec 016: required → optional
    [--no-oauth-consent]                         # 기존 플래그 보존 (OAuth env 명시되어도 consent skip)
```

## Inputs

| 옵션 | 타입 | 필수 | 기본값 | 의미 |
|---|---|---|---|---|
| `--alias` | string (`^[a-z0-9-]+$`) | ✅ | — | 학과 alias |
| `--display` | string (1~32자) | ✅ | — | 한국어 표시명 |
| `--channel-id-env` | string (`^TUBE_SCOUT_[A-Z0-9_]+$`) | ❌ (단, 다음 두 옵션과 함께 명시/생략) | None | agenix 환경변수명 |
| `--client-secret-env` | 동일 | ❌ | None | 동일 |
| `--api-key-env` | 동일 | ❌ | None | 동일 |
| `--no-oauth-consent` | flag | ❌ | False | OAuth env 가 명시되어 있어도 consent 단계 건너뛰기 |

## 옵션 명시 조합 4 가지 (FR-013 의 핵심)

| 조합 | channel-id-env | client-secret-env | api-key-env | 동작 | exit |
|---|---|---|---|---|---|
| A — Takeout 단독 | (없음) | (없음) | (없음) | departments.json 에 OAuth env 3 필드 null 로 저장. OAuth consent 단계 자동 skip. | 0 |
| B — spec 003 호환 OAuth | 명시 | 명시 | 명시 | env 3 개의 정의 여부 검증 (`_check_envs_present`) → OAuth consent 단계 진행 (`--no-oauth-consent` 명시 시 skip). | 0 |
| C — 일부만 명시 (예: 1개) | 명시 | (없음) | (없음) | stderr: "OAuth env 옵션은 3개 모두 명시되거나 모두 생략되어야 합니다 (현재 명시: ['channel-id-env'])" | 1 |
| D — 일부만 명시 (예: 2개) | 명시 | 명시 | (없음) | 동일 | 1 |

## Outputs (stdout)

기본 Rich 메시지 (한국어). `--json` 옵션은 spec 016 범위 밖 (스킵).

```
✓ 학과 등록 완료: nursing2 (테스트학과)
```

OAuth env 가 명시된 경우 (조합 B) consent 단계 후 추가 출력:

```
✓ OAuth 동의 완료: token_path=~/.config/tube-scout/tokens/nursing2.json
```

## Exit codes

| Code | 의미 | 트리거 |
|---|---|---|
| 0 | 성공 | 등록 + (필요시) OAuth consent 완료 |
| 1 | 검증 실패 | alias regex 위반, display 길이 위반, env 명 regex 위반, env 일부만 명시, 다른 등록부에 같은 alias 가 다른 channel_id 로 있음, env 명시되었으나 환경변수 정의 안 됨 |

## Side effects

- 조합 A: `departments.json` 에 새 row append (atomic write).
- 조합 B (consent 성공 시): `departments.json` + `~/.config/tube-scout/tokens/{alias}.json` (0600) + `channels.json` 의 새 row.
- 모든 조합: `operator_actions_repo` 에 `action=add_department, target_alias=<alias>, result=success|failure, detail=<reason>` 한 행 append (spec 008 의 기존 audit 보존).

## Error messages (English, fail-loud)

| 검증 | 메시지 |
|---|---|
| alias regex 위반 | `Alias must match pattern ^[a-z0-9-]+$ (got: <value>)` |
| display 길이 위반 | `Display name must be 1~32 characters (got: <length>)` |
| env 명 regex 위반 | `Env name '<value>' must match agenix prefix pattern TUBE_SCOUT_*` |
| env 일부 명시 | `OAuth env options must be all-or-nothing (specified: [...])` |
| env 명시 + 정의 안 됨 | `Environment variable '<NAME>' is not defined. Configure agenix and re-run.` |
| alias 비정합 | `Alias '<X>' already registered in <other_registry> with different channel_id. Resolve manually.` |

## Cross-Spec Boundary 검증 (B-2, B-7)

- B-2: `departments.json` 의 atomic write + mtime cache invalidation 흐름 보존. OAuth env 3 필드만 nullable 화.
- B-7: agenix `TUBE_SCOUT_*` 환경변수의 의미 변경 없음. 명시되면 검증, 생략되면 OAuth 자체 skip.

## Backward compatibility

- spec 003 시절 ZSH 스크립트로 `add-department` 를 호출하던 운영자는 3 env 를 모두 명시한 형태로 호출 중. 본 spec 변경 후에도 그 명령은 그대로 작동 (조합 B).
- spec 016 의 신규 추가는 조합 A 가능성뿐. 기존 호환성 break 없음.
