# Quickstart

신규 운영자가 30 분 이내에 한 학과 archive 를 처음부터 끝까지 처리하는 절차.

---

## 1. 사전 준비

### 1.1 환경 확인

```bash
nix develop          # flake devShell 진입 — PATH·LD_LIBRARY_PATH 자동 설정
tube-scout doctor    # 환경 진단: PASS/WARN/FAIL 표 출력
```

`doctor` 가 FAIL 을 보고하면 해당 항목을 먼저 해소한다. 일반적인 FAIL 원인과 조치:

| FAIL 항목 | 원인 | 조치 |
|---|---|---|
| `faster_whisper import` | `[asr]` extra 미설치 | `uv sync --extra asr` |
| `LD_LIBRARY_PATH (CUDA)` | GPU devShell 미사용 | `.envrc.local` 에 `use flake .#gpu` 추가 후 `direnv allow` |
| `sqlite3 version` | 시스템 sqlite3 < 3.35.0 | Nix devShell 내부에서 실행 (`nix develop` 후 재시도) |
| `which fpcalc` | chromaprint 미설치 | `nix develop` 진입 시 자동 제공 — devShell 밖에서 실행 중인 것 |

상세 raw 출력이 필요하면 `tube-scout doctor --verbose`.

### 1.2 GPU / CPU 환경 선택 (`.envrc.local`)

`.envrc.local` 은 gitignore 대상이므로 각 개발자가 독립적으로 관리한다.

| 파일 내용 | 효과 |
|---|---|
| (파일 없음 — 기본값) | CPU devShell — CUDA 없음, fpcalc·ffmpeg 포함 |
| `use flake .#gpu` | GPU devShell — cuDNN + NVRTC + CUDA 라이브러리 포함 |

GPU 를 사용하는 프로덕션 머신에서는 다음과 같이 설정:

```bash
echo 'use flake .#gpu' > .envrc.local
direnv allow
```

이후 `tube-scout doctor` 로 `LD_LIBRARY_PATH (CUDA)` 가 PASS 인지 확인.

### 1.3 의존성 설치

```bash
uv sync --extra asr   # faster-whisper (ASR) 포함 — 기본 설치 + GPU 런타임
# 개발 작업 시:
uv sync --extra asr --extra dev
```

install profile 전체 목록은 `pyproject.toml` 의 `[project.optional-dependencies]` 참조.

---

## 2. 학과 등록 확인

```bash
tube-scout admin list
```

처리 대상 alias 가 표시되어야 한다. 미등록 상태라면:

```bash
tube-scout admin add-department \
    --alias 간호 \
    --channel-id UCxxxxxxxxxxxxxxxxxx \
    --department-name "간호학과"
```

`channels.json` 과 `departments.json` 의 alias 가 불일치하면 `collect ingest` 가 exit 1 로 차단된다. 불일치 진단:

```bash
tube-scout admin list --json
```

---

## 3. Google Takeout archive 레이아웃

`collect ingest` 는 다음 디렉토리 구조를 가진 Takeout export 를 기대한다:

```
takeout-20260511T130817Z-3-001/
└── YouTube 및 YouTube Music/
    ├── 동영상/
    │   ├── 영상 제목.mp4
    │   └── 영상 제목.mp4
    └── 재생목록/
        └── 업로드한 동영상.csv   ← video_id ↔ 제목 매핑
```

`--takeout-dir` 에 압축 해제된 root (`takeout-20260511…/`) 경로를 전달한다.

---

## 4. 통합 인제스트 실행

```bash
tube-scout collect ingest \
    --takeout-dir ~/Downloads/takeout-20260511T130817Z-3-001 \
    --channel 간호
```

명령 한 번이 다섯 단계를 순서대로 실행한다:

| 단계 | 내용 | 성능 기준 |
|---|---|---|
| Step 1 | Takeout 적재 (CSV → SQLite + mp4 심볼릭링크) | ≤ 60 초 (실측 ~8 초) |
| Step 2 | 자막 생성 (faster-whisper ASR) | GPU 기준 mp4 당 약 90 초 |
| Step 3 | 음원 지문 추출 (chromaprint) | Step 2 와 WAV 공유 — 추가 +30 초 |
| Step 4 | 재시도 매니페스트 갱신 | < 1 초 |
| Step 5 | 영상 본체 정리 | 옵션 미지정 시 skip |

완료 시 Rich Table 요약이 출력된다:

```
┌─────────────────┬──────┬──────┬──────┬──────────┐
│ 단계            │ 처리 │ skip │ 실패 │ 소요 시간 │
├─────────────────┼──────┼──────┼──────┼──────────┤
│ 적재            │ 2554 │    - │    0 │       8s │
│ 자막 생성       │    9 │    0 │    0 │    ~14m  │
│ 음원 지문       │    9 │    0 │    0 │    ~30s  │
│ 매니페스트 갱신 │    0 │    - │    0 │      <1s │
│ 영상 정리       │ skip │    - │    - │        - │
└─────────────────┴──────┴──────┴──────┴──────────┘
```

### 4.1 산출물 검증

```bash
# 자막 JSON 개수 확인 (mp4 매핑 성공 수와 일치해야 함)
ls data/간호/02_analyze/transcripts/ | wc -l

# .tmp 잔재 없음
find data/간호/02_analyze/transcripts/ -name '*.tmp' | wc -l   # → 0

# DB 지문 행 수 확인
sqlite3 data/간호/content_reuse.db \
    "SELECT COUNT(*) FROM audio_fingerprint;"

# 자막 JSON 키 구조 검증
jq 'keys' data/간호/02_analyze/transcripts/*.json | sort -u
# 기대값: ["asr_quality_flags","duration","fetched_at","language","segments","source","video_id"]
```

### 4.2 ASR 프리셋 선택

`--preset` 옵션으로 ASR 디바이스를 고정할 수 있다. 미지정 시 GPU 메모리를 자동 감지한다:

| 조건 | 자동 선택 프리셋 |
|---|---|
| GPU 없음 또는 < 4 GiB | `cpu` |
| 4–16 GiB | `gpu-quantized` (int8_float16 — 권장) |
| ≥ 16 GiB 단일 GPU | `gpu-native` |
| ≥ 16 GiB 멀티 GPU | `gpu-pool` |

환경변수로 고정하려면 `.envrc.local` 에:

```bash
export TUBE_SCOUT_ASR_PRESET=gpu-quantized
```

---

## 5. 멱등 재실행

같은 archive 를 두 번째 실행하면 이미 처리된 자막·지문을 skip 한다:

```bash
time tube-scout collect ingest \
    --takeout-dir ~/Downloads/takeout-20260511T130817Z-3-001 \
    --channel 간호
```

기대 동작: Step 2/3 에서 **skip = N, 처리 = 0, 실패 = 0**, 전체 wall clock ≤ 30 초.

ASR 모델 교체 등으로 강제 재처리가 필요하면 `--force`:

```bash
tube-scout collect ingest \
    --takeout-dir ~/Downloads/takeout-20260511T130817Z-3-001 \
    --channel 간호 \
    --force
```

---

## 6. 영상 본체 삭제 (`--delete-source`)

분석 완료 후 archive 원본 mp4 를 정리하려면:

```bash
tube-scout collect ingest \
    --takeout-dir ~/Downloads/takeout-20260511T130817Z-3-001 \
    --channel 간호 \
    --delete-source
```

분석 완료 후 두 단계 prompt 가 표시된다:

1. **처리 실패 영상 자동 보존 알림** — 실패 영상은 표에 표시되고 삭제 대상에서 제외
2. **삭제 후보 확인** — `y` 로 응답하면 mp4 본체 + 심볼릭링크 unlink 후 audit 기록

처리 실패가 없어도 `n` 또는 Ctrl+C 로 취소 가능하며, 영상은 보존된다.

---

## 7. 재시도 매니페스트

처리에 실패한 영상은 `data/<alias>/retry_pending.json` 에 자동 기록된다:

```bash
cat data/간호/retry_pending.json
```

예시:

```json
{
  "schema_version": 2,
  "alias": "간호",
  "updated_at": "2026-05-17T02:57:32+00:00",
  "entries": [
    {
      "video_id": "abc123def45",
      "mp4_filename": "강의영상.mp4",
      "failed_stage": "asr",
      "failure_reason": "LibraryNotFoundError",
      "sub_reason": "LibraryNotFoundError",
      "last_attempt_at": "2026-05-17T02:57:32+00:00",
      "attempt_count": 1
    }
  ]
}
```

다음 `collect ingest` 호출 시 매니페스트의 영상이 우선 처리된다. `attempt_count` 가 5 이상이면 자동 재시도 대상에서 제외되고 `data/<alias>/manual_intervention_required.json` 으로 이동한다.

수동 점검 시나리오:

| 증상 | 원인 | 조치 |
|---|---|---|
| `asr` 반복 실패 | GPU 메모리 부족 | `--preset cpu` 로 강제 CPU 전환 |
| `fingerprint` 반복 실패 | mp4 파일 손상 | archive 재다운로드 |
| `attempt_count` ≥ 5 | 환경 문제 지속 | `manual_intervention_required.json` 확인 후 수동 처리 |

---

## 8. DB 심볼릭링크

`collect ingest` 는 canonical DB 파일에서 분석 경로로 심볼릭링크를 자동 생성한다:

```
data/<alias>/02_analyze/content_reuse.db → data/content_reuse.db
```

`content` 명령 등이 이 경로를 사용한다. 심볼릭링크가 깨진 경우:

```bash
# 실제 DB 경로 확인
ls -la data/간호/02_analyze/content_reuse.db

# 수동 재생성 (재실행으로 자동 복구)
tube-scout collect ingest --takeout-dir <path> --channel 간호 --dry-run
```

---

## 9. Audit CSV 와 복구 파일

적재 이력은 두 개의 CSV 에 기록된다:

| 파일 | 위치 | 내용 |
|---|---|---|
| `takeout_ingest_audit.csv` | `data/<alias>/01_collect/` | Takeout 적재 단계 결과 (video_id, result, reason, …) |
| `ingest_orchestrator_audit.csv` | `data/<alias>/01_collect/` | 통합 명령 전체 결과 (`sub_reason` 컬럼 포함) |

프로세스가 비정상 종료된 경우 버퍼에 남아 있던 행은 `.audit_recovery.csv` 로 자동 저장된다:

```bash
# 복구 파일 존재 여부 확인
ls data/간호/01_collect/.audit_recovery.csv 2>/dev/null && echo "복구 필요"

# 복구 파일 내용 확인 후 수동 병합
cat data/간호/01_collect/.audit_recovery.csv
# → 이후 ingest_orchestrator_audit.csv 에 행을 수동으로 추가하거나 재실행
```

---

## 10. 22 학과 일괄 운영

```bash
for alias in $(tube-scout admin list --alias-only); do
    tube-scout collect ingest \
        --takeout-dir ~/takeout-archives/${alias} \
        --channel "${alias}"
done
```

멱등 재호출 기준: 학과당 ~9 초 (적재 ~8 초 + skip 1 초). 22 학과 sequential 누적 약 3 분.

---

## 11. doctor 로 환경 재진단

운영 중 환경 이상이 의심될 때:

```bash
tube-scout doctor          # 간결 요약
tube-scout doctor --verbose  # nvidia-smi GPU 이름·메모리 포함 raw 출력
tube-scout doctor --exit-code  # FAIL 항목 있으면 exit 1 (CI/스크립트 연동)
```

---

## 12. 다음 단계

```
collect ingest 완료
→ tube-scout content reuse-detect --channel 간호   # 재사용 탐지
→ tube-scout analyze content-reuse --channel 간호  # 재사용 분석
→ tube-scout report channel --channel 간호         # 채널 리포트 생성
```

각 명령은 독립 실행 가능하며, 선행 데이터가 없으면 안내 메시지와 함께 exit 한다.
