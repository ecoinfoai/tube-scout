# CLI Contract: `tube-scout collect transcripts`

**Spec**: [../spec.md](../spec.md) | **FR**: FR-017, FR-018, FR-019 | **User Story**: US 4

## Command shape

```
tube-scout collect transcripts
    --channel <alias>                            # required
    [--source asr]                               # 기본값. 명시 권장.
    [--source youtube]                           # DEPRECATED — exit 2 + 차단
    [--model {tiny|base|small|medium|large-v3}]  # 기본 medium
    [--device {auto|cuda|cpu}]                   # 기본 auto
    [--compute-type {int8|float16|float32}]      # 기본 int8 (GPU) 또는 float32 (CPU)
    [--keep-audio]                               # 임시 wav 보존 (디버그용)
    [--db-path <path>]
    [--work-root <path>]
```

## Inputs

| 옵션 | 타입 | 필수 | 기본값 | 의미 |
|---|---|---|---|---|
| `--channel` | string | ✅ | — | 학과 alias |
| `--source` | enum `asr`/`youtube` | ❌ | `asr` | spec 013 의 source 옵션 |
| `--model` | enum | ❌ | `medium` | faster-whisper 모델 크기 |
| `--device` | enum | ❌ | `auto` | CUDA 가용 시 cuda, 없으면 cpu |
| `--compute-type` | enum | ❌ | `int8` (GPU) / `float32` (CPU) | CTranslate2 양자화 |
| `--keep-audio` | flag | ❌ | False | mp4 → wav 변환 후 wav 보존 |

## Outputs (stdout)

기본 Rich 진행 표시 + 완료 시 요약:

```
✓ ASR 완료: 9/9 영상 (모델=medium, 디바이스=cuda, compute=int8, 소요시간=4m 12s)
```

## Exit codes

| Code | 의미 | 트리거 |
|---|---|---|
| 0 | 성공 | 모든 mp4 ASR 완료 또는 mp4 부재 영상 audit 기록 완료 |
| 1 | 검증 실패 | alias 미등록, mp4 본체 0 개 (work_dir 가 비어 있음), 모델 로딩 실패 |
| 2 | Deprecated source | `--source youtube` 명시 시 (FR-018) |

## `--source youtube` deprecation 동작 (FR-018)

명시 시 stderr 메시지 + exit 2:

```
ERROR: --source youtube 는 2026-05-12 결정으로 폐기되었습니다.
       Takeout 단독 운영 모델에서는 자막을 faster-whisper ASR 로 직접 생성합니다.
       --source asr 가 기본값이므로 옵션을 생략하거나 명시적으로 --source asr 를 사용하세요.
```

deprecation 은 단순 경고가 아니라 **명시적 차단** — silent fallback 으로 ASR 가 실행되지 않음 (Constitution II 일치).

## mp4 부재 영상 처리 (FR-019)

`data/{alias}/동영상/` 에 mp4 본체가 symlink 되지 않은 영상에 대해서는 ASR 단계 자체가 invoke 되지 않는다. 대신 audit 에 다음 row 가 추가:

| stage | video_id | result | reason | mp4_filename | elapsed_ms |
|---|---|---|---|---|---|
| asr | `<video_id>` | skip | no_mp4_in_archive | n/a | 0 |

본 동작은 collect takeout 의 `mp4_absent_count` 와 정합 — 같은 video_id 에 대해 collect takeout 이 `no_mp4_in_archive` 로 audit 한 영상은 collect transcripts 가 다시 같은 reason 으로 audit.

## Cross-Spec Boundary 검증 (B-6)

- B-6: spec 013 의 `--source asr` / `--source youtube` 분기를 단일 경로로 단순화. CLI 옵션 시그니처 자체는 보존 (`--source` 옵션과 enum 자체는 그대로). 의미만 변경 — `youtube` 는 차단값.

## ASR 모델 선택 가이드 (사용자 메모리 참조)

- 본 작업 머신 (RTX 3060 6GB): `medium` 모델까지 안전. `large-v3` 는 메모리 한계에 가까워 권장하지 않음.
- 별도 GPU 서버 (22 학과 본격 적재용): `large-v3` 사용 가능. 본 spec 범위 밖.

## Idempotence guarantees

- 같은 영상에 대해 두 번 호출: 자막 파일 (`data/{alias}/02_transcripts/<video_id>.json`) 이 이미 존재하면 ASR 재실행 없이 skip + audit `result=skip, reason=already_transcribed` 기록.
- `--keep-audio=False` 의 경우 임시 wav 는 ASR 완료 후 자동 삭제 (WavLifecycle 컨텍스트 매니저).

## 본 spec 의 변경 표면

- FR-017: `--source` 옵션 미명시 시 ASR 자동 선택 (기존 동작 유지 또는 명시 변경).
- FR-018: `--source youtube` 차단 (신규 deprecation 분기).
- FR-019: mp4 부재 영상 audit 일관성 (기존 동작 유지 + 명시 검증).
