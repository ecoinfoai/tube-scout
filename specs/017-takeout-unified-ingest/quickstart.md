# Quickstart: Takeout 통합 적재와 운영 효율화

**Spec**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md) | **Date**: 2026-05-16

본 quickstart 는 spec 017 구현 완료 후 학과 운영자가 한 학과 archive 한 묶음을 신규 통합 명령 (`collect ingest`) 으로 처음부터 끝까지 처리하는 절차다. 기존 spec 016 의 quickstart (`collect takeout` 분리 호출 흐름) 는 backward compat 으로 유지되지만, **권장 운영 흐름은 본 문서의 단일 통합 명령으로 일원화**된다.

---

## §0. 사전 준비

### §0.1 환경

```bash
nix develop                       # flake devShell 진입
uv sync --extra asr --extra dev   # faster-whisper + pytest 동기화
```

본 spec 은 신규 PyPI 의존성 0 건이므로 spec 013 / spec 016 의 환경 동기화로 충분.

### §0.2 GPU 환경 확인

```bash
nvidia-smi                        # RTX 3060 6GB 인식
python -c "from faster_whisper import WhisperModel; m = WhisperModel('tiny', device='cuda', compute_type='int8'); print('OK')"
```

ASR 단계에서 faster-whisper 가 GPU 디바이스에 모델을 로드한다. medium 모델 권장 (본 작업 머신 기준 안전).

### §0.3 학과 등록 확인

```bash
tube-scout admin list
```

본 문서의 예시는 `nursing` alias 가 이미 등록되어 있다고 가정한다. 등록되지 않았다면 spec 016 의 quickstart §0.5 절차로 먼저 등록.

---

## §1. 통합 명령 한 번으로 한 학과 처리

### §1.1 기본 호출 (영상 보존)

```bash
tube-scout collect ingest \
    --takeout-dir data/takeout-20260511T130817Z-3-001 \
    --channel nursing
```

본 명령은 다음 5 단계를 순차로 수행한다.

| 단계 | 내용 |
|---|---|
| Step 1 | Takeout 적재 (csv → SQLite + mp4 symlink + audit row) |
| Step 2 | 자막 생성 (faster-whisper ASR, mp4 매핑된 영상만) |
| Step 3 | 음원 지문 추출 (chromaprint, mp4 매핑된 영상만) |
| Step 4 | 재시도 매니페스트 갱신 (실패 영상 → retry_pending.json) |
| Step 5 | 영상 본체 정리 (옵션 미지정으로 자동 skip) |

예상 종료 시점에 다음 Rich Table 이 표시된다:

```
┌────────────────────┬───────────┬──────────┬──────────┐
│ 단계               │ 성공      │ 실패     │ 소요 시간 │
├────────────────────┼───────────┼──────────┼──────────┤
│ 적재               │ 2554      │ 0        │ ~8s       │
│ 자막 생성          │ 9         │ 0        │ <약 N분>  │
│ 음원 지문          │ 9         │ 0        │ <약 N분>  │
│ 매니페스트 갱신    │ 0 추가    │ 0 해소   │ <1s      │
│ 영상 정리          │ skip      │ -        │ -        │
└────────────────────┴───────────┴──────────┴──────────┘

✓ 통합 명령 완료 (alias=nursing, 총 소요 약 N분)
```

> **SC-001 회귀 검증 포인트**: 적재 단계 ≤ 60s. 실측 (2026-05-16 T037): 실적재 평균 8.3s / dry-run 평균 1.64s. spec 016 baseline 1061s 대비 약 644 배 개선.

### §1.2 영상 본체 정리까지 (옵션 지정)

분석 단계 종료 후 archive 의 mp4 본체와 작업 디렉토리의 symlink 를 정리하려면 `--delete-source` 옵션을 명시한다.

```bash
tube-scout collect ingest \
    --takeout-dir data/takeout-20260511T130817Z-3-001 \
    --channel nursing \
    --delete-source
```

분석 단계 종료 시점에 다음 두 단계 prompt 가 등장한다.

#### Stage 1 — 처리 실패 영상 자동 보존 알림 (응답 받지 않음)

```
[처리 실패 영상 — 자동 보존됨]
┌──────────────┬─────────────────────────┬──────────┬─────────────────────────┐
│ video_id     │ 영상 제목                │ 실패 단계 │ 실패 사유                │
├──────────────┼─────────────────────────┼──────────┼─────────────────────────┤
│ (실패 영상 0건 시 본 표 자체가 생략)                                      │
└──────────────┴─────────────────────────┴──────────┴─────────────────────────┘
```

처리 실패 영상이 있다면 표로 표시되고, 다음 통합 명령 호출에서 자동 재시도 대상이 된다. 표시는 정보 제공이며 운영자 응답을 요구하지 않는다.

#### Stage 2 — 삭제 후보 영상 yes/no 확인

```
[삭제 후보 — 모든 분석 단계 성공한 영상]
- archive 의 mp4 본체: 9 개
- data/nursing/동영상/ 의 symlink: 9 개
- 회수 가능 용량: 약 9.9 GB

Delete 9 source mp4 files? (y/N): _
```

운영자 응답에 따른 동작:

- `y` → 모든 후보 영상 unlink + audit 로그 기록
- `n` 또는 응답 없음 → 모든 영상 보존

### §1.3 적재 단계만 측정 (`--dry-run`)

자막·지문·삭제를 건너뛰고 적재 단계 시간만 측정하려면:

```bash
tube-scout collect ingest \
    --takeout-dir data/takeout-20260511T130817Z-3-001 \
    --channel nursing \
    --dry-run
```

SQLite write 가 발생하지 않는다. 적재 elapsed_seconds 를 baseline 측정용으로 사용 가능.

---

## §2. 재시도 매니페스트로 처리 실패 영상 따라잡기

### §2.1 매니페스트 위치 확인

```bash
cat data/nursing/retry_pending.json
```

예시 출력:

```json
{
  "schema_version": 1,
  "alias": "nursing",
  "updated_at": "2026-05-16T08:43:42+09:00",
  "entries": [
    {
      "video_id": "abc123def45",
      "title": "5-1 임경민 간호연구세미나 8주차 1차시",
      "failed_stage": "transcript",
      "failure_reason": "model_loading_failed",
      "last_attempt_at": "2026-05-16T08:43:42+09:00",
      "attempt_count": 1
    }
  ]
}
```

`entries` 가 비어 있으면 모든 영상이 성공적으로 처리됨을 의미.

### §2.2 자동 재시도

다음에 같은 alias 로 `collect ingest` 를 호출하면 매니페스트의 영상이 우선 처리 대상으로 잡힌다. 성공하면 매니페스트의 해당 entry 가 자동 제거되고, 실패하면 `attempt_count` 가 증가한다.

### §2.3 수동 점검 신호

한 영상의 `attempt_count` 가 5 회 이상이면 자동 재시도 대상에서 제외된다. 이 경우 운영자가 다음을 점검:

- GPU 메모리 부족 → ASR 모델을 small 로 downgrade
- mp4 파일 corruption → archive 재다운로드
- 자막 출력 디렉토리 권한 → 0600 점검

매니페스트의 row 를 직접 편집하거나, JSON 을 통째로 비우면 매니페스트가 초기화된다 (다음 통합 명령에서 새로 시작).

---

## §3. 기존 분리 명령과의 관계 (Backward Compat)

본 spec 의 통합 명령 도입은 기존 분리 명령 (`collect takeout`, `collect transcripts`, `collect fingerprint`, `collect process-audio`, `collect audio-extract`) 의 호출 표면을 변경하지 않는다.

- 기존 자동화 스크립트가 분리 명령에 의존하면 그대로 작동
- 단 quickstart 의 권장 흐름은 본 문서의 통합 명령으로 일원화
- spec 013 / spec 016 의 quickstart 는 archived 상태로 참조용

---

## §4. 비정합 alias 검증 (spec 016 의 FR-015 보존)

`channels.json` 과 `departments.json` 의 alias 가 다른 channel_id 를 가리키면 `collect ingest` 도 spec 016 의 `collect takeout` 과 같은 형식으로 차단된다.

```
ERROR: alias 'nursing' mismatch between channels.json and departments.json — analysis commands blocked. Run 'tube-scout admin list --json' to inspect.
```

exit code 1. 운영자가 `tube-scout admin list --json` 으로 비정합 사실을 확인하고 한 등록부의 alias 를 정정해야 함.

---

## §5. 운영자 체크리스트

spec 017 구현 완료 후 운영자가 따라할 매뉴얼 체크:

- [ ] `tube-scout collect ingest --channel nursing --takeout-dir <path>` 가 exit 0 으로 정상 완료 (US1)
- [ ] 적재 단계가 본 작업 머신에서 60 초 이내에 완료 (SC-001, 본 머신 실측 평균 8.3s, dry-run 1.64s)
- [ ] 같은 archive 두 번째 호출 시 `new=0`, 자막·지문 재생성 0 (SC-004)
- [ ] 한 호출 안에서 같은 영상의 음원 디코딩이 1 회 (Step 2 자막과 Step 3 지문이 같은 임시 음원을 공유) (SC-005)
- [ ] 단계별 소요 시간이 모두 양의 값으로 표시 (SC-006)
- [ ] `--delete-source` 옵션 없으면 prompt 등장 안 함, 영상 보존
- [ ] `--delete-source` 옵션 + 운영자 `y` 시 archive mp4 + symlink 모두 정리 + audit 기록
- [ ] `--delete-source` 옵션 + 운영자 `n` 시 영상 보존 + audit `confirmed_no` 기록
- [ ] 처리 실패 영상이 있으면 Stage 1 표에 100% 노출 + 삭제 후보에서 자동 제외 (SC-007)
- [ ] 처리 실패 영상이 `retry_pending.json` 에 자동 정리, 다음 호출에서 우선 재시도 (SC-008)
- [ ] 기존 분리 명령 (`collect takeout`, `collect transcripts`, etc.) 이 통합 명령 도입 후에도 정상 작동 (backward compat)

---

## §6. 22 학과 확장 시 운영 패턴 (참고)

본 spec 의 적재 효율화 (1 분 이내) 와 통합 명령 도입은 22 학과 누적 처리의 운영 시간을 단축한다. 예상 운영 패턴:

```bash
for alias in dept-a dept-b ... nursing ... dept-w; do
    tube-scout collect ingest \
        --takeout-dir "data/takeout-<part>-${alias}" \
        --channel "${alias}" \
        --delete-source
    # 운영자가 학과별 prompt 에 yes/no 응답
done
```

학과별 적재 단계 평균 8.3s + 자막+지문 ~55s = 통합 명령 평균 64.3s (T037 실측, RTX 3060 + 표준 PC). 22 학과 sequential 누적 시 약 24 분 ((22 × 64.3s) / 60 ≈ 23.6 분) — 영업일 1 일 충분. 멱등 재호출 (이미 적재된 archive) 은 학과당 ~1.6s 로 22 학과 36s 처리. 실패 영상은 학과별 retry_pending.json 에 격리되어 다음 cycle 에서 자동 재시도.

단 GPU 메모리 / 디스크 / 네트워크 자원의 동시 처리 한계는 별도 spec 의 범위.
