# Quickstart: Takeout 적재 모듈 재작성 검증 흐름

**Spec**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md) | **Date**: 2026-05-15

본 quickstart 는 spec 016 구현 완료 후 운영자가 처음부터 끝까지 따라할 수 있는 검증 절차다. 간호학과 9 영상 샘플 archive 를 입력으로 사용한다.

---

## §0. 사전 준비

### §0.1 환경

```bash
nix develop                       # flake devShell 진입
uv sync --extra asr --extra dev   # faster-whisper + pytest 동기화
```

> **주의**: `uv sync --extra asr` 만 실행하면 `[dev]` 묶음이 제거된다. 검증을 위해서는 두 extra 를 동시에 동기화.

### §0.2 입력 데이터 확인

```bash
ls data/takeout-20260511T130817Z-3-001/Takeout/  # 1개 폴더: 'YouTube 및 YouTube Music'
```

본 quickstart 의 입력:
- archive 크기: 약 9.9 GB
- mp4 본체: 9 개 (간호학과 일부)
- 채널 전체 영상 메타: 2554 개 (csv 13 파일에 분할)
- 자막: 동봉되지 않음 (spec 016 의 핵심 사실, R-5)

### §0.3 GPU 환경 확인

```bash
nvidia-smi                        # RTX 3060 6GB 인식
python -c "from faster_whisper import WhisperModel; m = WhisperModel('tiny', device='cuda', compute_type='int8'); print('OK')"
```

위 sanity check 는 import 만 확인하는 게 아니라 **`tiny` 모델 가중치를 CUDA 디바이스에 int8 로 실제 로드**까지 성공해야 OK. 디바이스 누락 또는 CUDA 환경 부재 시 즉시 raise 되므로 `print('OK')` 가 출력되면 본 작업 머신의 GPU + CTranslate2 + faster-whisper 스택이 완전히 작동함을 보증한다. 본 머신은 medium 모델까지 안전. large-v3 는 GPU 서버 단계로 분리.

---

## §0.5 학과 등록

### Takeout 단독 (OAuth env 없이)

```bash
tube-scout admin add-department \
    --alias nursing \
    --display "부산보건대 간호학과"
```

예상 출력:
```
✓ 학과 등록 완료: nursing (부산보건대 간호학과)
```

`departments.json` 에 entry 가 atomic write 로 추가됨. OAuth env 3 필드는 모두 `null`.

### spec 003 호환 (OAuth 자격 명시)

agenix 환경변수가 모두 정의되어 있는 경우:

```bash
tube-scout admin add-department \
    --alias nursing \
    --display "부산보건대 간호학과" \
    --channel-id-env TUBE_SCOUT_CH_ID_NURSING \
    --client-secret-env TUBE_SCOUT_OAUTH_CLIENT \
    --api-key-env TUBE_SCOUT_API_KEY
```

OAuth consent 단계가 자동 진행되어 `~/.config/tube-scout/tokens/nursing.json` (0600) 토큰이 발급된다.

### 등록 확인

```bash
tube-scout admin list
```

예상 Rich table 출력 (Takeout 단독 등록의 경우):

```
alias   │ display_name        │ channel_id │ source       │ consistency
────────┼─────────────────────┼────────────┼──────────────┼─────────────
nursing │ 부산보건대 간호학과    │ —          │ departments  │ ok
```

`--json` 옵션:

```bash
tube-scout admin list --json | jq .
```

비정합 (channels.json 과 departments.json 양쪽에 같은 alias 가 다른 channel_id 로 있는 경우) 가 발견되면 stderr 에 `WARNING: alias 'nursing' mismatch (...)` 라인이 출력되지만 명령 자체는 exit 0.

---

## §1. Takeout archive 적재

### §1.1 Dry-run

```bash
tube-scout collect takeout \
    --takeout-dir data/takeout-20260511T130817Z-3-001 \
    --channel nursing \
    --dry-run
```

예상 출력 (Rich table) — 본 결정 후 spec 016 의 핵심 성공 신호:

```
적재 결과 (DRY-RUN)
─────────────────────────────────
channel_id              UCnh3tm9uQkyA260cAHfl9rg
channel_alias           nursing
total_videos            2554
new_videos              0           (dry-run 이므로 항상 0)
high_confidence_mappings 9
medium_confidence_mappings 0
ambiguous_mappings      0
unmapped_filenames      0
ignored_csv_count       26          (동영상 녹화 13 + 동영상 텍스트 13)
mp4_present_count       9
mp4_absent_count        2545
elapsed_seconds         <측정값>
dry_run                 true
```

> **🚨 SC-001 회귀 검증 포인트**: 본 명령이 0 exit code 로 완주하는 것이 spec 016 의 1차 검증 목표다. 현재 master(v0.5.0) 상태에서는 `Missing columns in 채널.csv: {'채널 이름'}` 으로 첫 1초에 차단된다.

### §1.2 분할 csv 의 의미 (FR-021)

한 archive part 의 `동영상 메타데이터/` 폴더에는 다음 13 csv 가 들어 있다.

| 파일 | 영상 수 |
|---|---|
| `동영상.csv` (본 파일) | 200 |
| `동영상(1).csv` ~ `동영상(11).csv` | 각 200 |
| `동영상(12).csv` (마지막 chunk) | 154 |
| 합계 | 2554 |

본 spec 의 적재 모듈은 정확 glob 패턴 (`동영상.csv` + `동영상(N).csv`) 으로 13 파일을 union 하여 dedup 한다 (R-3). 같은 폴더의 `동영상 녹화*.csv`, `동영상 텍스트*.csv` 26 개는 무시 정책 (`_IGNORED_PATTERNS`, FR-011) 으로 audit `ignored_by_policy` row 로 기록된다.

### §1.3 다중 archive part (FR-020)

자교 한 학과의 mp4 총량이 약 2.4 TB 라서 모든 part 를 한 번에 풀 수 없다. 운영 시나리오:

```bash
# 1차 part (현재 사용한 3-001)
tube-scout collect takeout --takeout-dir <part 3-001> --channel nursing

# 2차 part (나중에 별도 다운로드)
tube-scout collect takeout --takeout-dir <part 3-002> --channel nursing
```

두 part 의 메타 csv 가 모두 채널 전체 2554 영상을 담고 있어도 (R-9 가정) 멱등 적재 (FR-009) 로 두 번째 실행에서 `new_videos=0`. 새 mp4 본체만 symlink 추가.

> **R-9 미확인**: 다중 archive 환경에서 메타가 모든 part 에 동봉되는지 한 part 에만 동봉되는지 사용자 미확인. 멱등 적재로 양쪽 모두 안전.

### §1.4 실적재

```bash
tube-scout collect takeout \
    --takeout-dir data/takeout-20260511T130817Z-3-001 \
    --channel nursing
```

dry-run 결과를 검토한 뒤 `--dry-run` 없이 실행. 차이:

- SQLite v4 에 channel_metadata 1 행 + video_metadata 2554 행 INSERT.
- `data/nursing/channel_meta.json` + `data/nursing/videos_meta.json` atomic write.
- `data/nursing/동영상/<mp4_filename>.mp4` 9 개 symlink 생성.
- `data/nursing/audit.csv` 에 row 약 2580 개 append:
  - 9 success (mp4 매칭)
  - 2545 skip / no_mp4_in_archive
  - 26 skip / ignored_by_policy (녹화/텍스트 csv)
  - 0 skip / unknown_privacy_value (본 데이터에는 한글 값이 모두 매핑 표 안)

### §1.5 멱등성 검증 (FR-009, SC-005)

```bash
tube-scout collect takeout \
    --takeout-dir data/takeout-20260511T130817Z-3-001 \
    --channel nursing
```

같은 명령을 한 번 더 실행. 예상:

- `new_videos=0`, `mp4_added=0`.
- SQLite 행 수 변화 0.
- audit.csv 에 같은 row 들이 한 번 더 append (append-only).

---

## §2. 자막 ASR (FR-017)

```bash
tube-scout collect transcripts --channel nursing
```

`--source asr` 가 기본값이므로 옵션 생략 가능. 9 mp4 에 대해 faster-whisper medium 모델로 자막 생성.

예상 출력:

```
ASR 진행 [████████████████████] 9/9
✓ ASR 완료: 9/9 영상 (모델=medium, 디바이스=cuda, compute=int8, 소요시간=N분 N초)
```

`data/nursing/02_transcripts/<video_id>.json` 9 개 파일 생성.

### §2.1 `--source youtube` deprecation 확인 (FR-018)

```bash
tube-scout collect transcripts --channel nursing --source youtube
```

예상 출력:

```
ERROR: --source youtube 는 2026-05-12 결정으로 폐기되었습니다.
       Takeout 단독 운영 모델에서는 자막을 faster-whisper ASR 로 직접 생성합니다.
       --source asr 가 기본값이므로 옵션을 생략하거나 명시적으로 --source asr 를 사용하세요.
```

exit code 2.

### §2.2 mp4 부재 영상 처리 (FR-019)

mp4 본체가 동봉되지 않은 2545 영상은 ASR 단계 자체가 invoke 되지 않으며 audit 에 다음 row 가 추가:

```
stage,video_id,result,reason,...
asr,abc123,skip,no_mp4_in_archive,...
asr,xyz789,skip,no_mp4_in_archive,...
```

다른 archive part 가 풀려 mp4 본체가 발견되면 그때 ASR 가 실행된다.

---

## §3. 비정합 검증 (FR-015)

운영자가 두 등록부에 같은 alias 를 다른 channel_id 로 등록한 경우의 시나리오. 정상 운영에서는 발생하지 않지만 마이그레이션 단계에서 가능.

### §3.1 비정합 상황 만들기 (테스트용)

```bash
# departments.json 에는 nursing 이 OAuth env 명시 등록 (channel_id_env 가 UCabc 가리킴)
# channels.json 에는 nursing 이 UCdef 로 직접 저장
```

### §3.2 `admin list` 출력

```bash
tube-scout admin list
```

stdout (Rich table):

```
alias   │ display_name        │ channel_id │ source │ consistency
────────┼─────────────────────┼────────────┼────────┼─────────────
nursing │ 부산보건대 간호학과    │ UCdef      │ both   │ mismatch
```

stderr:

```
WARNING: alias 'nursing' mismatch (channels.json=UCdef, departments.json=UCabc)
```

`admin list` 자체는 exit 0.

### §3.3 분석 명령에서의 차단 (FR-015 후반부)

```bash
tube-scout collect takeout --takeout-dir <path> --channel nursing
```

stderr:

```
ERROR: alias 'nursing' mismatch between channels.json and departments.json — analysis commands blocked. Run 'tube-scout admin list --json' to inspect.
```

exit code 1.

---

## §4. 회귀 테스트 실행 (SC-008)

```bash
uv run pytest tests/unit/test_takeout_ingest.py \
              tests/unit/test_admin_add_department.py \
              tests/unit/test_admin_list_union.py \
              tests/unit/test_privacy_mapping.py \
              tests/integration/test_takeout_e2e_nursing.py \
              tests/integration/test_idempotent_part_load.py \
              tests/integration/test_asr_single_source.py \
              tests/contract/ -v
```

예상: 결함 8 개 (1·2·3·4·6·7·8·11) 모두에 대한 failing-then-passing 회귀 테스트가 PASS.

---

## §5. 운영자 체크리스트

spec 016 구현 완료 후 운영자가 따라할 매뉴얼 체크:

- [ ] `tube-scout admin list` 가 새 alias 를 즉시 보여준다 (SC-004).
- [ ] `tube-scout collect takeout --dry-run` 이 0 exit code 로 완주 (SC-001).
- [ ] 실적재 후 SQLite `video_metadata` 행 수 = 2554 (SC-002).
- [ ] privacy_status NULL 행 = 0 (SC-002).
- [ ] 같은 archive 2 회 적재 시 두 번째에 `new_videos=0` (SC-005).
- [ ] `tube-scout collect transcripts` 가 옵션 없이 ASR 단일 경로로 동작 (SC-006).
- [ ] `--source youtube` 명시 시 exit 2 + 명확 메시지 (SC-006).
- [ ] IngestResult 출력에 `elapsed_seconds`, audit 에 `elapsed_ms` 가 양의 값 (SC-009).
- [ ] 회귀 테스트 8 개 모두 PASS (SC-008).
