# Quickstart: spec 018 운영자 가이드

**Spec**: [spec.md](./spec.md) | **Plan**: [plan.md](./plan.md) | **Status**: Draft (Phase 1)

본 quickstart 는 spec 017 의 quickstart §5 KNOWN LIMITATION (멱등 부분 실패) 의 후속 PATCH 운영 안내다. 새 운영자가 본 문서 1 회 read 후 멱등 동작을 직접 검증할 수 있다.

## 1. 사전 준비 (spec 017 인계)

| 항목 | 출처 | 확인 명령 |
|---|---|---|
| Python 3.11 + `[asr]` extras 설치 | `flake.nix` devShell | `uv run python -c "import faster_whisper; print(faster_whisper.__version__)"` |
| GPU 사용 가능 (RTX 3060 권장) | NVIDIA driver + libcublas.so.12 | `nvidia-smi` |
| 학과 alias 등록 | spec 003 / 016 (`channels.json` / `departments.json`) | `tube-scout admin list` |
| SQLite v4 schema 초기화 | spec 013 v4 migration | `tube-scout admin migrate --dry-run` (없으면 마이그레이션 권고) |

## 2. 첫 호출 (fresh archive)

```bash
tube-scout collect ingest \
    --takeout-dir ~/Downloads/takeout-2026-05-14-nursing/ \
    --alias 간호 \
    --copy
```

### 2.1 기대 출력 (RTX 3060 + 간호학과 9 mp4 기준)

- 적재 단계: **약 8 초** (spec 017 SC-001 메모이즈 효과)
- 자막 단계: **약 14 분** (faster-whisper large-v3 int8_float16)
- 지문 단계: 자막과 동일 WAV 공유, 약 + 30 초
- 매니페스트 갱신: ≤ 1 초
- 영상 정리: skip (`--delete-source` 미지정)

전체 wall clock 약 **14m 36s**. 종료 후:

| 산출물 | 위치 | 개수 (간호학과 9 mp4 기준) |
|---|---|---|
| Transcript artifact (json) | `data/간호/02_analyze/transcripts/*.json` | 9 |
| Audio fingerprint row (DB) | `data/간호/content_reuse.db` 의 `audio_fingerprint` 테이블 | 9 |
| 임시 WAV | `data/간호/tmp_wav/*.wav` | **0** (즉시 정리 — spec 017 C-1) |
| retry_pending.json | `data/간호/retry_pending.json` | 신규 실패 entries (정상 시 0) |

### 2.2 산출물 검증 명령

```bash
# 자막 json 9 개 + .tmp 잔재 0 개
ls data/간호/02_analyze/transcripts/ | wc -l   # → 9
find data/간호/02_analyze/transcripts/ -name '*.tmp' | wc -l   # → 0

# DB row count 9
sqlite3 data/간호/content_reuse.db \
    "SELECT COUNT(*) FROM audio_fingerprint;"   # → 9

# 모든 transcript 가 7 키를 가짐
jq -e 'keys == ["asr_quality_flags", "duration", "fetched_at", "language", "segments", "source", "video_id"]' \
    data/간호/02_analyze/transcripts/*.json
```

## 3. 두 번째 호출 — 멱등 검증 (SC-018-1)

```bash
time tube-scout collect ingest --takeout-dir ~/Downloads/takeout-2026-05-14-nursing/ --alias 간호 --copy
```

### 3.1 기대 출력

```text
▶ Step 1/5: Takeout 적재
  → 영상 2554, mp4 매핑 9 high, 소요 8s
▶ Step 2/5: 자막 생성 (faster-whisper)
▶ Step 3/5: 음원 지문 추출 (chromaprint)
▶ Step 4/5: 재시도 매니페스트 갱신
▶ Step 5/5: 영상 본체 정리 [skip]

┌─────────────────┬──────┬──────┬──────┬──────────┐
│ 단계            │ 처리 │ skip │ 실패 │ 소요 시간 │
├─────────────────┼──────┼──────┼──────┼──────────┤
│ 적재            │ 2554 │    - │    0 │       8s │
│ 자막 생성       │    0 │    9 │    0 │     0.1s │
│ 음원 지문       │    0 │    9 │    0 │     0.1s │
│ 매니페스트 갱신 │ 0추가│ 0해소│    - │      <1s │
│ 영상 정리       │ skip │    - │    - │        - │
└─────────────────┴──────┴──────┴──────┴──────────┘
✓ 통합 명령 완료 (alias=간호, 총 소요 ~9s)
```

### 3.2 검증 항목

- **전체 명령 wall clock ≤ 30 초** (`time` 출력 real 시간) — 적재 ~8s + 자막·지문 skip ≤ 2s
- **자막·지문 단계 wall clock ≤ 2 초** (SC-018-1 측정 범위: `_run_transcript_and_fingerprint` 호출 기준)
- 자막 / 지문 행의 **skip 9 / 처리 0 / 실패 0**
- 매니페스트 추가 0 / 해소 0
- 임시 WAV 파일 0 개 (디코딩 skip — FR-018E)
- GPU 메모리 사용량 0 (faster-whisper 모델 로드 skip — Q4 결정)

검증 명령:

```bash
# WAV 디코딩 발생 여부 (0 이어야 함)
find data/간호/tmp_wav/ -name '*.wav' 2>/dev/null | wc -l   # → 0

# 자막 json mtime 변화 없음 (멱등)
stat -c '%Y' data/간호/02_analyze/transcripts/*.json | sort -u   # → 단일 timestamp
```

## 4. 강제 재처리 — `--force` (SC-018-3)

ASR 모델을 교체했거나 chromaprint 파라미터를 변경한 후 같은 archive 를 재처리:

```bash
tube-scout collect ingest \
    --takeout-dir ~/Downloads/takeout-2026-05-14-nursing/ \
    --alias 간호 \
    --copy \
    --force
```

### 4.1 기대 동작

- 멱등 가드 우회, archive 내 모든 영상 재처리
- wall clock 약 14m 36s (fresh 처리에 준함)
- `audio_fingerprint` row 수 유지 = 9 (`INSERT OR REPLACE` 의 PK 단일성)
- transcript json mtime 갱신
- retry_pending.json 자동 해소 (이전 실패 entry 가 성공으로 전환되면 제거)

### 4.2 검증 명령

```bash
# row 수 유지
sqlite3 data/간호/content_reuse.db "SELECT COUNT(*) FROM audio_fingerprint;"   # → 9

# 모든 transcript mtime 이 호출 직후로 갱신
stat -c '%Y' data/간호/02_analyze/transcripts/*.json
# (현재 시각 이후의 timestamp 9 개)
```

## 5. 22 학과 운영 환산 (SC-018-4)

본 PATCH 의 SC-018-4 는 22 학과 모두에 대한 멱등 재호출의 **자막·지문 단계** 누적 wall clock 이 **≤ 44 초** (= 22 × 2 초) 임을 보장한다. Takeout 적재 포함 전체 명령 기준으로는 ≤ 660 초 (22 × 30 초). 현재 (spec 017 baseline) 자막·지문 단계 누적 약 5 시간 24 분 대비 **99% 절감**.

22 학과 일괄 재호출 한 줄 script (참고):

```bash
for alias in $(tube-scout admin list --alias-only); do
    tube-scout collect ingest \
        --takeout-dir ~/takeout-archives/${alias}/ \
        --alias ${alias}
done
```

22 학과 누적 측정은 본 PATCH 의 acceptance 조건이 아니다 (1 학과 측정 + 선형 환산으로 SC-018-4 충족 검증).

## 6. spec 017 quickstart §5 KNOWN LIMITATION 갱신

spec 017 의 quickstart §5 에 기록된 "두 번째 호출 시 자막·지문 재처리 14m36s" 는 본 PATCH 완료 시점에 **RESOLVED** 다. 새 운영자는 본 quickstart §3 의 검증 단계로 멱등 동작을 직접 확인할 수 있다.

historical 기록 유지를 위해 spec 017 quickstart §5 의 원문은 보존하되 본 PATCH 의 spec.md FR-018G 가 요구하는 "RESOLVED in spec 018" 표시는 implementation 단계 (tasks.md T-NN) 에서 적용된다.

## 7. Troubleshooting

| 증상 | 가능한 원인 | 조치 |
|---|---|---|
| 두 번째 호출이 14 분 이상 걸림 | 멱등 가드 미동작 (regression) | `data/<alias>/02_analyze/transcripts/` 의 json 파일 수와 DB row 수 둘 다 9 인지 확인. 한쪽만 9 면 부분 영구화 상태 — 정상이며 한 단계만 재처리 |
| transcript json 이 .tmp 로 남음 | atomic write 실패 (디스크 full / permission 등) | 디스크 여유 확인, 권한 확인 (디렉토리 owner = ${USER}). `.tmp` 는 다음 호출이 자동 정리 |
| `INSERT OR REPLACE` 가 row 수를 변경 | 외부 코드가 INSERT 했을 가능성 | `audio_fingerprint` PK = video_id 확인 (`PRAGMA index_list(audio_fingerprint)`) |
| `--force` 후에도 wall clock 이 ≤ 2 초 | 의도와 다른 경로 — 멱등 가드를 우회하지 못함 | implementation 회귀, `_check_already_processed` 의 `force` 파라미터 전달 확인 |
| Rich Table 이 깨짐 (행 5 개가 아닌 다른 수) | spec 017 의 5-row Table 변경 | `_print_summary_table` regression 확인 |
| `retry_pending.json` 의 video_id 가 계속 남음 | mp4 파일이 archive 에 부재 (파일 삭제 또는 export 누락) | retry_pending entries 의 video_id 중 mp4 파일이 부재하면 `skipped_no_mp4` 로 처리되어 자동 해소되지 않음 — 운영자가 mp4 복구 후 재호출 또는 `retry_pending.json` 수동 편집으로 해당 entry 제거 필요 |

## 8. 다음 단계

본 quickstart 의 §2 / §3 / §4 검증이 모두 통과하면 SC-018-1 / SC-018-2 / SC-018-3 의 외부 acceptance 가 충족된다. 추가로:

- `/speckit.tasks` → tasks.md 생성 → TDD 사이클 진입
- spec 011 의 재사용 탐지 명령에 본 PATCH 의 산출물을 입력으로 전달 → schema 동치성 (FR-018H) 실측
- 22 학과 일괄 운영 시 본 quickstart §5 의 한 줄 script 적용
