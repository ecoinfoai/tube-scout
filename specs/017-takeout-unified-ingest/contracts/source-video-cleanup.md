# Contract: Source Video Cleanup (`--delete-source` 두 단계 prompt)

**Spec**: [spec.md](../spec.md) — FR-011, FR-012, FR-013, FR-014, SC-003, SC-007
**Data model**: [data-model.md](../data-model.md) — E-4 CleanupResult, E-5 FailureEntry

본 contract 는 `collect ingest --delete-source` 옵션 지정 시 활성화되는 두 단계 prompt 의 운영자 노출 형식, 응답 처리 흐름, 그리고 unlink 동작의 정밀 규약을 정의한다.

### 어휘 매핑

- **Stage 1** = 운영자에게 처리 실패 영상 표를 보여주는 첫 번째 화면 (응답 받지 않음)
- **Stage 2** = 삭제 후보 영상의 yes/no 확인을 받는 두 번째 화면

본 contract 와 tasks.md 는 영문 "Stage 1 / Stage 2" 를 사용하고, spec.md 와 quickstart.md 는 한글 "첫 번째 화면 / 두 번째 화면" 또는 "첫 번째 prompt / 두 번째 prompt" 를 사용한다. 의미는 같다.

## 진입 조건

본 흐름은 다음 두 조건이 모두 만족될 때만 활성화된다.

1. 운영자가 `collect ingest` 호출 시 `--delete-source` 옵션 (또는 동등한 명시 옵션) 을 지정 (FR-011)
2. 분석 단계 (적재·자막·지문) 가 모두 종료됨 (정상 완료 또는 부분 실패 모두 포함)

옵션 미지정 시 본 흐름 자체가 등장하지 않고, 영상은 모두 보존된다 (silent 가 아닌 명시적 no-op).

## 두 단계 흐름

### Stage 1 — 처리 실패 영상 표시 (응답 받지 않음)

자막 또는 지문 단계가 실패한 영상의 목록을 Rich Table 로 운영자에게 표시한다.

```
[처리 실패 영상 — 자동 보존됨]
┌──────────────┬─────────────────────────┬──────────┬─────────────────────────┐
│ video_id     │ 영상 제목                │ 실패 단계 │ 실패 사유                │
├──────────────┼─────────────────────────┼──────────┼─────────────────────────┤
│ abc123def45  │ 5-1 임경민 간호연구...    │ asr      │ model_loading_failed    │
│ xyz789ghi67  │ 10-2 정연진 기본간호...   │ fingerprint │ chromaprint_timeout │
└──────────────┴─────────────────────────┴──────────┴─────────────────────────┘

다음 영상은 처리 실패로 인해 삭제 후보에서 자동 제외되었습니다 (재시도 매니페스트에 기록됨).
```

- 실패 영상이 0 건이면 본 stage 의 표는 생략하고, "처리 실패 영상 없음 — 모든 영상이 삭제 후보입니다" 한 줄만 출력.
- 표 자체는 정보 제공이며 운영자 응답을 요구하지 않음.
- audit 로그에 `stage=source_video_cleanup, result=success, reason=presented_failures, score=<failure_count>` row 1 개 append.

### Stage 2 — 삭제 후보 확인 prompt

모든 분석 단계가 성공한 영상의 mp4 본체 + symlink 를 한 표로 표시하고 yes/no 응답을 받는다.

```
[삭제 후보 — 모든 분석 단계 성공한 영상]
- archive 의 mp4 본체: 8 개
- data/nursing/동영상/ 의 symlink: 8 개
- 회수 가능 용량: 약 8.9 GB

Delete 8 source mp4 files? (y/N): _
```

운영자가 영상 목록을 자세히 보고 싶다면 별도 명령 (`ls data/nursing/동영상/`) 으로 확인 가능. 본 stage 의 출력은 총량 + 카운트만 표시하여 명령 흐름이 너무 길어지지 않게 한다.

prompt 응답:

- `y` 또는 `yes` (case-insensitive) → 삭제 진행
- `n` 또는 `no` (case-insensitive) → 영상 보존
- 응답 없음 (EOF / Ctrl+D) → 보존 (정책: 응답 없음은 거부로 간주, audit `reason=timeout`)
- Ctrl+C → 보존 + audit `reason=interrupted`

### Timeout 정책

본 prompt 는 별도의 시간 제한을 두지 않고 운영자 응답을 **무한 대기**한다. Rich `Confirm.ask` 의 default 동작을 그대로 따른다. 즉 위 4 분기 중 "응답 없음" 은 wall-clock timeout 으로 발생하지 않으며, stdin 의 EOF 또는 Ctrl+D 입력으로만 도달한다. 22 학과 일괄 처리 시 운영자가 prompt 를 무한정 방치하는 시나리오는 본 spec 의 범위 밖이며, 별도의 자동화 흐름이 필요하면 향후 spec 에서 `--auto-yes` 또는 `--timeout-seconds` 옵션을 추가할 수 있다.

## CleanupResult 출력 형식

### yes 응답 + 성공

```
✓ 영상 삭제 완료: 8 개 (회수 용량 8.9 GB)
  - archive mp4 unlink: 8
  - symlink 정리: 8
  - 처리 실패 보존: 2 개 (retry_pending.json 에 기록됨)
```

audit 로그:
- `stage=source_video_cleanup, result=success, reason=confirmed_yes` row 1 개
- `stage=source_video_cleanup, result=success, reason=deleted, mp4_filename=<filename>` row N 개

### yes 응답 + 일부 unlink 실패 (예: 파일 잠금)

```
⚠ 영상 삭제 부분 완료: 6 / 8 성공 (회수 용량 6.7 GB)
  - 실패 2 개: file locked 또는 I/O error (audit 로그 확인)
```

audit 로그:
- 성공 6 개: `reason=deleted` row 6 개
- 실패 2 개: `reason=delete_failed_locked` 또는 `reason=delete_failed_io` row 2 개

### no 응답

```
영상 삭제 거부됨 — 모든 영상 파일 보존
```

audit 로그:
- `stage=source_video_cleanup, result=success, reason=confirmed_no` row 1 개

### timeout / EOF

```
응답 없음 — 영상 파일 보존
```

audit 로그:
- `stage=source_video_cleanup, result=success, reason=timeout` row 1 개

### Ctrl+C interrupt

```
사용자 중단 — 영상 파일 보존
```

audit 로그:
- `stage=source_video_cleanup, result=success, reason=interrupted` row 1 개

## Unlink 동작의 정밀 규약

### 삭제 후보

운영자가 yes 응답한 경우 다음 두 위치의 파일을 모두 unlink:

1. **archive 의 mp4 본체**: spec.md FR-013 의 archive 안 경로 (예: `data/takeout-20260511T130817Z-3-001/Takeout/YouTube 및 YouTube Music/동영상/<filename>.mp4`)
2. **작업 디렉토리의 symlink**: `data/<alias>/동영상/<filename>.mp4` (spec 016 의 boundary B-8)

### 삭제 안 함

다음은 삭제 후보에서 제외:

- **SQLite v4 의 video_metadata row**: 메타데이터는 영상 본체와 무관하게 영구 보존
- **자막 파일**: `data/<alias>/02_transcripts/<video_id>.json` 등 (영상 본체가 사라져도 자막은 분석에 사용)
- **지문 데이터**: SQLite 의 `comparison_results` 또는 별도 파일
- **audit CSV row**: append-only 보존

### 처리 실패 영상

자막 또는 지문이 실패한 영상은 Stage 1 의 표에 표시되고, Stage 2 의 삭제 후보에서 자동 제외. 영상 본체와 symlink 모두 보존 + retry_pending.json 에 entry 추가.

## Function Signatures

`src/tube_scout/services/source_video_cleanup.py` 가 본 흐름을 구현한다.

### `present_failure_table(failures: list[FailureEntry], *, console: Console = ...) -> None`

처리 실패 영상의 표를 Rich Table 로 출력. 응답 받지 않음.

```python
def present_failure_table(
    failures: list[FailureEntry],
    *,
    console: Console | None = None,
) -> None:
    """Display failure table to operator (no input prompt).

    Logs one audit row (stage=source_video_cleanup,
    reason=presented_failures) regardless of failure count.
    """
```

### `confirm_and_cleanup(candidates: list[CleanupCandidate], *, prompt_io: PromptIO = ..., audit_writer: AuditWriter, ...) -> CleanupResult`

삭제 후보 영상에 대해 두 번째 prompt 를 띄우고, 응답에 따라 unlink 수행. CleanupResult 반환.

```python
def confirm_and_cleanup(
    candidates: list[CleanupCandidate],
    *,
    prompt_io: PromptIO | None = None,
    audit_writer: AuditWriter,
) -> CleanupResult:
    """Show second prompt and perform unlink on yes.

    Records every transition (confirmed_yes / confirmed_no / timeout
    / interrupted / deleted / delete_failed_*) in audit log.
    """
```

## PromptIO Protocol (테스트 mocking 용)

```python
class PromptIO(Protocol):
    def ask_yes_no(self, message: str, *, default: bool = False) -> bool: ...
```

production 구현은 Rich `Confirm.ask`. 단위 테스트의 mocking 구현은 lambda 또는 stub.

## Acceptance Matrix

| 시나리오 | 입력 | 기대 결과 |
|---|---|---|
| 실패 0 + yes | failures=[], 운영자 `y` | Stage 1 의 표 생략, Stage 2 prompt, unlink 모든 영상, audit `confirmed_yes` + `deleted` × N |
| 실패 N + yes | failures=N 개, 운영자 `y` | Stage 1 의 표 표시, Stage 2 prompt, unlink 성공 영상만, 실패 영상은 보존, audit `presented_failures` + `confirmed_yes` + `deleted` × (total-N) |
| 실패 0 + no | failures=[], 운영자 `n` | Stage 1 의 "처리 실패 영상 없음" 메시지, Stage 2 prompt, unlink 0, audit `confirmed_no` |
| 실패 N + no | failures=N, 운영자 `n` | Stage 1 표 표시, Stage 2 prompt, unlink 0, audit `presented_failures` + `confirmed_no` |
| EOF | EOF on prompt | unlink 0, audit `timeout` |
| Ctrl+C | KeyboardInterrupt on prompt | unlink 0, audit `interrupted`, exit 0 (interrupt 가 명령 자체를 종료하지 않음) |
| 파일 잠금 | yes + 일부 파일 locked | locked 파일은 audit `delete_failed_locked`, 나머지는 `deleted` |
| I/O 오류 | yes + 일부 파일 I/O 오류 | I/O 파일은 audit `delete_failed_io`, 나머지는 `deleted` |
| --delete-source 미지정 | 옵션 부재 | 본 contract 자체 활성화 안 됨, Stage 1/2 모두 등장 안 함 |
