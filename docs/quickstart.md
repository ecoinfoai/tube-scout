# Quickstart

신규 운영자가 한 학과 archive 를 처음부터 끝까지 처리하는 절차.

---

## 1. GPU / ASR 환경 설정

### 1.1 devShell 진입 방법 비교

| 방법 | 명령 | GPU (CUDA) | 특징 |
|---|---|---|---|
| direnv (권장) | `.envrc.local` 설정 후 `cd` 재진입 | `.envrc.local` 내용에 따름 | 디렉토리 진입 시 자동 활성화 |
| 수동 | `nix develop` | CPU devShell | GPU 없음 |
| 수동 GPU | `nix develop .#gpu` | GPU devShell | cuDNN + NVRTC 포함 |

**direnv 권장 이유**: 터미널을 열 때마다 자동으로 올바른 devShell 이 활성화된다. 수동 `nix develop` 는 새 shell 세션을 열거나 누락하기 쉽다.

### 1.2 `.envrc.local` 생성 (GPU 머신)

```bash
# 프로젝트 루트에서 실행
echo 'use flake .#gpu' > .envrc.local
direnv allow
```

`.envrc.local` 은 gitignore 대상이므로 각 개발자가 독립적으로 관리한다.

> **중요**: `direnv allow` 직후 현재 shell 의 `LD_LIBRARY_PATH` 는 즉시 갱신되지 않는다.
> **새 터미널을 열거나** (`exec $SHELL` 또는 터미널 재시작) `direnv reload` 로 환경을 다시 불러와야 한다.
> `direnv reload` 후에도 기존에 열려 있던 터미널은 이전 환경을 그대로 유지한다.

CPU 머신 (GPU 없음) 은 `.envrc.local` 을 생성하지 않거나 내용을 비워 둔다:

```bash
# CPU 전용 — 파일 없음이 기본값
# 또는 명시적으로:
echo '# use flake .#gpu' > .envrc.local   # 주석 처리
direnv allow
```

### 1.3 환경 검증 3단계 (D-1.b + E-2.a)

devShell 진입 후 다음 순서로 검증한다:

```bash
# 1단계: devShell 안에 있는지 확인
echo $IN_NIX_SHELL    # → "impure" 또는 "pure"

# 2단계: CUDA 라이브러리 경로 확인 (GPU 머신)
echo $LD_LIBRARY_PATH | tr ':' '\n' | grep -i cuda

# 3단계: tube-scout doctor 전체 진단
tube-scout doctor
```

`doctor` 출력 예시 (GPU 정상 환경):

```
          tube-scout doctor
┌──────────────────────────────┬────────┬─────────────────────────────┐
│ 항목                         │ 상태   │ 세부 정보                   │
├──────────────────────────────┼────────┼─────────────────────────────┤
│ Python interpreter           │ PASS   │ 3.11.15 — /path/to/python   │
│ devShell (Nix)               │ PASS   │ IN_NIX_SHELL='impure'       │
│ faster_whisper import        │ PASS   │ v1.1.0                      │
│ LD_LIBRARY_PATH (CUDA)       │ PASS   │ /nix/store/.../cudnn/lib    │
│ which fpcalc                 │ PASS   │ /nix/store/.../fpcalc       │
│ which ffmpeg                 │ PASS   │ /nix/store/.../ffmpeg       │
│ which sqlite3                │ PASS   │ /nix/store/.../sqlite3      │
│ nvidia-smi                   │ PASS   │ /run/opengl-driver/bin/...  │
│ torch.cuda.is_available      │ PASS   │ True — 1 device(s)          │
│ sqlite3 version              │ PASS   │ 3.46.1                      │
└──────────────────────────────┴────────┴─────────────────────────────┘
```

상세 raw 출력: `tube-scout doctor --verbose` (nvidia-smi GPU 이름·메모리 포함).
CI / 스크립트 연동: `tube-scout doctor --exit-code` (FAIL 항목 있으면 exit 1).

일반적인 FAIL 원인과 조치:

| FAIL 항목 | 원인 | 조치 |
|---|---|---|
| `faster_whisper import` | `[asr]` extra 미설치 | `uv sync --extra asr` |
| `LD_LIBRARY_PATH (CUDA)` | GPU devShell 미사용 | `.envrc.local` 에 `use flake .#gpu` + 새 터미널 |
| `sqlite3 version` | 시스템 sqlite3 < 3.35.0 | Nix devShell 내부에서 실행 (`nix develop` 후 재시도) |
| `which fpcalc` | devShell 밖에서 실행 중 | `nix develop` 진입 후 재시도 |

> **SQLite < 3.35.0 에러**: devShell 밖에서 tube-scout 를 실행하면
> `sqlite3.OperationalError: near "RETURNING": syntax error` 가 발생한다.
> `nix develop` 또는 direnv 로 devShell 에 진입한 후 재실행한다.

### 1.4 의존성 설치

```bash
# 개발 / CI 환경
uv sync --extra asr --extra dev

# 운영 환경 (시스템 PATH 에 tube-scout 명령 설치)
uv tool install --editable '.[asr]'
```

`uv tool install` 은 가상환경 없이 `tube-scout` 명령을 PATH 에 직접 등록한다.
개발 중에는 `uv run tube-scout` 을 쓰고, 운영 서버에서는 `uv tool install` 을 권장한다.

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

### 2.1 임시 CSV fake row 절차 (R-2.a)

`업로드한 동영상.csv` 가 없는 Takeout export (재생목록 미포함) 는 적재 가능하지만
video_id ↔ 제목 매핑이 없어 자막·지문 단계가 skip 된다.
이 경우 임시로 fake row 를 만들어 매핑을 수동으로 추가할 수 있다:

```bash
# 임시 CSV 생성 (헤더 + fake row 1개)
cat > /tmp/fake_upload.csv <<'EOF'
재생목록 ID,동영상 ID,동영상 제목,만든 날짜
PLxxxxxxxxxxxxxxxx,VIDEO_ID_HERE,강의 제목,2026-01-01
EOF

# 실제 Takeout 구조에 배치
cp /tmp/fake_upload.csv \
   ~/Downloads/takeout-20260511T130817Z-3-001/"YouTube 및 YouTube Music"/재생목록/"업로드한 동영상.csv"
```

> **삭제 의무**: fake row 를 포함한 CSV 는 처리 완료 후 반드시 제거하거나 원본으로 교체한다.
> 그렇지 않으면 다음 적재 시 video_id 와 실제 mp4 파일이 불일치하여 잘못된 매핑이 생성된다.

---

## 3. Google Takeout archive 레이아웃 (R-12.a)

`collect ingest` 는 다음 디렉토리 구조를 가진 Takeout export 를 기대한다:

```
takeout-20260511T130817Z-3-001/          ← --takeout-dir 에 이 경로를 전달
└── YouTube 및 YouTube Music/            ← 자동 감지 (한국어·영어 모두 지원)
    ├── 동영상/                          ← mp4 파일 위치
    │   ├── 강의영상_1.mp4
    │   └── 강의영상_2.mp4
    └── 재생목록/
        └── 업로드한 동영상.csv          ← video_id ↔ 제목 매핑 (필수)
```

자동 감지 실패 시 다음 에러가 출력된다:

```
ERROR: YouTube directory not found in takeout root.
Expected one of: 'YouTube 및 YouTube Music', 'YouTube and YouTube Music'
Takeout root: /path/to/takeout-...
```

이 메시지가 보이면 `--takeout-dir` 경로가 올바른지 확인한다 (`takeout-.../` 의 **직접 부모** 가 아니라 **압축 해제 root** 를 전달해야 한다).

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

### 4.3 faster-whisper CUDA 런타임 에러 해석 (F-3a)

자막 생성 단계에서 다음 에러가 발생하면 CUDA 라이브러리 문제다:

```
faster-whisper CUDA runtime error: Library libcublas.so.12 is not found or cannot be loaded
```

분류:

| 에러 문자열 | 원인 | 조치 |
|---|---|---|
| `libcublas.so.12 is not found` | GPU devShell 미사용 | `.envrc.local` 확인 + 새 터미널 |
| `CUDA error: no kernel image` | GPU compute capability 불일치 | `--preset cpu` 로 강제 전환 |
| `out of memory` | GPU VRAM 부족 | `--preset gpu-quantized` 또는 `--preset cpu` |

에러가 발생하면 해당 영상이 `retry_pending.json` 에 기록된다. 환경을 고친 후 재호출하면 자동으로 재시도한다.

---

## 5. 멱등 재실행 (R-8.a)

같은 archive 를 두 번째 실행하면 이미 처리된 자막·지문을 skip 한다:

```bash
time tube-scout collect ingest \
    --takeout-dir ~/Downloads/takeout-20260511T130817Z-3-001 \
    --channel 간호
```

기대 동작: Step 2/3 에서 **skip = N, 처리 = 0, 실패 = 0**, 전체 wall clock ≤ 30 초.

두 번째 실행에서 `처리 = 0` (`new = 0`) 이 보이면 멱등 가드가 정상 동작하는 것이다.
`처리 > 0` 이 보이면 이전 실행이 완전히 완료되지 않았거나 `--force` 가 지정된 경우다.

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

예시 (schema_version 2):

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

**schema_version 1 → 2 자동 마이그레이션**: 이전 spec (016 이하) 에서 생성된 `retry_pending.json` 은 `schema_version: 1` 이다. `collect ingest` 실행 시 자동으로 v2 로 업그레이드되며, 원본은 `retry_pending.json.bak.<timestamp>` 로 백업된다. `.bak.<ts>` 파일은 마이그레이션 이전 상태의 안전망으로, 정상 동작 확인 후 삭제해도 된다.

다음 `collect ingest` 호출 시 매니페스트의 영상이 우선 처리된다. `attempt_count` 가 5 이상이면 자동 재시도 대상에서 제외되고 `data/<alias>/manual_intervention_required.json` 으로 이동한다.

수동 점검 시나리오:

| 증상 | 원인 | 조치 |
|---|---|---|
| `asr` 반복 실패 | GPU 메모리 부족 또는 CUDA 라이브러리 없음 | `--preset cpu` 또는 §1.2 GPU 환경 설정 |
| `fingerprint` 반복 실패 | mp4 파일 손상 | archive 재다운로드 |
| `attempt_count` ≥ 5 | 환경 문제 지속 | `manual_intervention_required.json` 확인 후 수동 처리 |

---

## 8. DB 심볼릭링크 (ADV-57)

`collect ingest` 는 canonical DB 파일에서 분석 경로로 심볼릭링크를 자동 생성한다:

```
data/<alias>/02_analyze/content_reuse.db → ../../content_reuse.db
                                           (canonical: data/content_reuse.db)
```

`content` 명령 등이 이 상대경로 심볼릭링크를 사용한다. 심볼릭링크가 깨진 경우:

```bash
# 심볼릭링크 상태 확인
ls -la data/간호/02_analyze/content_reuse.db

# 수동 cleanup 후 재생성 (dry-run 으로 실제 DB 쓰기 없이 symlink 만 복구)
rm -f data/간호/02_analyze/content_reuse.db
tube-scout collect ingest \
    --takeout-dir <path> \
    --channel 간호 \
    --dry-run
```

`--dry-run` 은 SQLite write 를 수행하지 않지만 심볼릭링크는 생성한다.

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
ls data/간호/01_collect/.audit_recovery.csv 2>/dev/null && echo "복구 파일 발견 — 수동 처리 필요"

# 복구 파일 내용 확인
cat data/간호/01_collect/.audit_recovery.csv

# 수동 병합 (헤더 제외 행만 추가)
tail -n +2 data/간호/01_collect/.audit_recovery.csv \
    >> data/간호/01_collect/ingest_orchestrator_audit.csv

# 병합 확인 후 복구 파일 제거
rm data/간호/01_collect/.audit_recovery.csv
```

복구 없이 단순히 재실행하는 것도 가능하다 (멱등 재실행으로 audit 행이 새로 기록됨).

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
tube-scout doctor            # 간결 요약
tube-scout doctor --verbose  # nvidia-smi GPU 이름·메모리 포함 raw 출력
tube-scout doctor --exit-code  # FAIL 항목 있으면 exit 1 (CI/스크립트 연동)
```

---

## 12. 다음 단계 (R-11.a)

`collect ingest` 완료 후 권장 후속 명령:

```bash
# 교수 채널 매핑 (콘텐츠 분석 전 필수)
tube-scout content professor map --channel 간호

# 콘텐츠 재사용 탐지
tube-scout content reuse-detect --channel 간호

# 재사용 분석 리포트 생성
tube-scout analyze content-reuse --channel 간호

# 채널 리포트 생성
tube-scout report channel --channel 간호
```

각 명령은 독립 실행 가능하며, 선행 데이터가 없으면 안내 메시지와 함께 exit 한다.
