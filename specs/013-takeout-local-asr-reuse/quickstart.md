# Quickstart: Takeout 기반 강의 영상 재사용 판정 + 자막 KB Export

**Spec**: [spec.md](./spec.md) · **Plan**: [plan.md](./plan.md) · **Data Model**: [data-model.md](./data-model.md)

본 문서는 운영자가 0에서 시작해 한 교수 단위 M-nC2 보고서를 받기까지의 4단계 경로 + 자막 KB export 보조 경로를 정리한다.

---

## 0. 환경 설정 (1회)

### 0.1 devShell 선택

`flake.nix` 는 두 개의 devShell을 제공한다:

- `devShells.default` (CPU): `chromaprint`, `ffmpeg`, `zlib`, `stdenv.cc.cc.lib`. faster-whisper의 CPU/int8 경로면 충분.
- `devShells.gpu` (unfree 허용 필요): default의 모든 것 + `cudaPackages.cudnn` + `cudaPackages.cuda_nvrtc`. faster-whisper GPU 경로(cuda:0 / cuda:1 워커 풀)에 필수.

```bash
# CPU/디버깅
nix develop

# 운영 GPU 서버
NIXPKGS_ALLOW_UNFREE=1 nix develop --impure .#gpu
# 또는 .envrc.local에 `use flake .#gpu` 한 줄 + direnv allow
```

### 0.2 Python 의존성

`pyproject.toml` `[project.optional-dependencies]` 에 `asr` 신규 분리:

```toml
asr = [
    "faster-whisper>=1.0.0,<2.0.0",
]
all = [
    "tube-scout[ml,pdf,asr]",
]
```

설치:

```bash
uv sync --extra asr
# 또는 분석·보고서까지 한 번에:
uv sync --extra all
```

### 0.3 faster-whisper 모델 사전 다운로드 (권장, 오프라인 운영 시 필수)

```bash
# 약 1.5 GB (int8 양자화). 최초 1회.
huggingface-cli download Systran/faster-whisper-large-v3 --local-dir ~/.cache/huggingface/hub/models--Systran--faster-whisper-large-v3
```

`$HF_HOME` 미설정 시 기본 `~/.cache/huggingface/`. 운영 GPU 서버가 인터넷 격리된 환경이면 PoC 머신에서 다운로드 후 캐시 디렉터리 rsync로 전송.

### 0.4 Takeout export 신청 + 압축 해제

운영자 본인 Google 계정에서 [Google Takeout](https://takeout.google.com)으로 YouTube 데이터 export 신청 → 며칠 후 다운로드 → 작업 디렉터리에 압축 해제:

```bash
mkdir -p data/takeout-20260511T130817Z-3-001
cd data/takeout-20260511T130817Z-3-001
unzip ~/Downloads/takeout-20260511T130817Z-3-001.zip
ls Takeout/'YouTube 및 YouTube Music'/
# 동영상/  동영상 메타데이터/  채널/  댓글/  재생목록/  구독정보/  시청 기록/
```

분할 part(`3-002`, `3-003`, …)가 있으면 각각 별도 디렉터리에 풀어두기 — 단계 1에서 누적 ingestion.

### 0.5 자교 alias 등록 확인

```bash
tube-scout admin list
# nursing  ...
```

미등록 시 (학과 등록 + agenix env 매핑 — spec 008):

```bash
tube-scout admin add-department \
    --alias nursing \
    --display "간호학과" \
    --channel-id-env  TUBE_SCOUT_CHANNEL_ID_NURSING \
    --client-secret-env TUBE_SCOUT_CLIENT_SECRET_NURSING \
    --api-key-env TUBE_SCOUT_API_KEY_NURSING
```

---

## 1. Takeout ingestion (Phase 1)

```bash
tube-scout collect takeout \
    --takeout-dir data/takeout-20260511T130817Z-3-001/Takeout \
    --channel nursing
```

**산출**:
- `data/<alias>/channel_meta.json` + `data/<alias>/videos_meta.json`.
- `data/<alias>/videos/` 하위에 mp4 심볼릭 링크 (기본) 또는 `--copy` 시 물리 복사본.
- SQLite `content_reuse.db` v4 적재 — `channel_metadata` 1 row + `video_metadata` N rows + `processing_status` N rows (status=`collected`, caption_source=NULL).
- 매핑 ambiguous 케이스는 `data/<alias>/01_collect/_ambiguous_mappings.csv` 로 surface.
- audit `data/<alias>/01_collect/takeout_ingest_audit.csv`.

### 1.1 ambiguous 매핑 운영자 해결

```bash
vi data/<alias>/01_collect/_ambiguous_mappings.csv
# resolved_video_id 컬럼에 결정 입력 후 저장.
```

같은 명령 재실행 → 결정 반영, 자동 매핑 단계 우회.

### 1.2 분할 Takeout part 누적

```bash
# part-002, part-003 받았을 때
tube-scout collect takeout --takeout-dir data/takeout-...-3-002/Takeout --channel nursing
tube-scout collect takeout --takeout-dir data/takeout-...-3-003/Takeout --channel nursing
```

같은 video_id는 첫 ingestion의 메타 권위 유지 (idempotent). 새 video_id만 누적.

---

## 2. 오디오 추출 + 지문 + STT 통합 (Phase 1·2)

### 2.1 학과 전체 운영 경로 (권장)

```bash
# PoC 머신에서 9 영상 검증
tube-scout collect process-audio \
    --channel nursing \
    --preset poc-laptop \
    --all-takeout

# 운영 GPU 서버 (cuda:0 + cuda:1 워커 풀)
tube-scout collect process-audio \
    --channel nursing \
    --preset prod-a6000-pool \
    --all-takeout
```

**영상별 라이프사이클**: [mp4 → 16 kHz mono WAV 추출 → chromaprint 지문 → faster-whisper STT → Text Normalizer → WAV 삭제]. `--keep-audio` 시 WAV 보존(디버깅).

**Progress**: TTY면 rich.progress 바, 비-TTY(cron / nohup)면 매 영상 한 줄 stdout — `[transcripts] video_id=sUJbkkYzNGc N=1/2555 elapsed=12s ETA=...`

### 2.2 단계별 디버깅 경로 (분리 모드)

```bash
# WAV만 추출 (캐시 누적, 디버깅 용)
tube-scout collect audio-extract --channel nursing --all-takeout --audio-cache-dir ./audio_cache/

# 지문만 (WAV 입력)
tube-scout collect fingerprint --source local --channel nursing --input-kind wav_16k --all-takeout

# ASR만 (WAV 입력)
tube-scout collect transcripts --source asr --channel nursing --preset poc-laptop --all-takeout
```

### 2.3 ASR 실패 영상 재시도

```bash
tube-scout collect transcripts --source asr --channel nursing --preset prod-a6000-pool --retry-failed
# asr_failed → asr_in_progress 직접 atomic 전이, 다른 status에는 영향 없음.
```

### 2.4 자막 정규화 단독 (auto-normalize off로 처리했을 때)

```bash
tube-scout process normalize-transcripts --channel nursing
# transcripts/ 폴더 전체 스캔, transcripts_normalized/ 생성.
```

---

## 3. nC2 분석 (Phase 3)

```bash
tube-scout analyze content-reuse \
    --channel nursing \
    --professor "정광석" \
    --mode M-nC2 \
    --layer-a-seconds 30.0 \
    --layer-b-threshold 0.30
```

**산출**: SQLite `comparison_results` row(쌍 수만큼) + `match_spans` row + `pair_checkpoint` UPDATE + audit `analyze_audit.csv`.

**resume**:

```bash
# Ctrl+C 후 다시
tube-scout analyze content-reuse --channel nursing --professor "정광석" --mode M-nC2 --resume
```

`pair_checkpoint` 가 미완 쌍 이어붙기 보장.

---

## 4. 보고서 (Phase 3)

```bash
tube-scout report content-reuse \
    --channel nursing \
    --professor "정광석" \
    --mode M-nC2 \
    --top-k 50 \
    --sort-by i2-cosine \
    --format both
```

**산출**: `projects/{job-id}/03_report/정광석_nC2_report.html` + `정광석_nC2_report.pdf`.

### 4.1 첫 30일 운영 (default)

```bash
# 부록 임계 미설정 — 모든 쌍 부록 진입 + 분포 히스토그램 본문 포함
tube-scout report content-reuse --channel nursing --professor "정광석" --mode M-nC2
```

운영자가 본문 분포 히스토그램으로 axis별 변별력 관찰 → 30일 후 임계값 결정.

### 4.2 운영 첫 30일 이후

```bash
# 운영자가 직접 결정한 per-metric 임계
tube-scout report content-reuse \
    --channel nursing \
    --professor "정광석" \
    --mode M-nC2 \
    --appendix-threshold-i2-cosine 0.85 \
    --appendix-threshold-i6-longest-contiguous 300.0 \
    --appendix-threshold-audio-fp-hamming 50
# OR semantics: 한 임계라도 초과하면 부록 진입.
```

### 4.3 sort axis 변경

```bash
tube-scout report content-reuse --channel nursing --professor "정광석" --mode M-nC2 --sort-by audio-fp-hamming
# 음원 지문 거리 내림차순 — re-recorded-same-content 패턴 찾기 좋음.
```

---

## 5. 자막 KB Export (Phase 4)

### 5.1 단일 영상

```bash
tube-scout transcript export \
    --video-id sUJbkkYzNGc \
    --format md \
    --with-meta \
    --clean-fillers \
    --output ./kb_export/sUJbkkYzNGc.md
```

### 5.2 채널 전체

```bash
tube-scout transcript export-bulk \
    --channel nursing \
    --all \
    --format jsonl \
    --output-dir ./kb_export/nursing/
```

산출: `./kb_export/nursing/<video_id>.jsonl` × N개. 외부 KB 도구(검색 인덱스 / RAG / LLM fine-tuning)의 입력으로 그대로 사용.

---

## 6. 일반 운영 시나리오

### 6.1 학과 전체 신규 part 누적 → 분석 → 보고서

```bash
# part-004 도착
tube-scout collect takeout --takeout-dir data/takeout-...-3-004/Takeout --channel nursing
tube-scout collect process-audio --channel nursing --preset prod-a6000-pool

# 분석 재실행 (force 또는 신규 영상만 자동 incremental)
tube-scout analyze content-reuse --channel nursing --professor "정광석" --mode M-nC2 --resume

# 보고서 재생성
tube-scout report content-reuse --channel nursing --professor "정광석" --mode M-nC2
```

### 6.2 작업 디렉터리 외장 디스크로 이전

DB는 손대지 않고 CLI 인자만 새 경로로 변경:

```bash
# data/ 디렉터리를 /mnt/external/tube-scout/data/ 로 rsync
rsync -av data/ /mnt/external/tube-scout/data/

# 분석·보고서 재실행 시 새 경로 그대로
tube-scout analyze content-reuse --channel nursing --professor "정광석" --mode M-nC2 --resume
```

`mp4_relative_path` 는 채널 work_dir 기준 상대 경로이므로 절대 경로 변경 자유.

### 6.3 운영 GPU 서버 인계

```bash
# PoC 머신에서 모델 캐시 다운로드 후 운영 서버로 전송
rsync -av ~/.cache/huggingface/hub/ user@prod-gpu-server:~/.cache/huggingface/hub/

# 운영 서버에서 ssh detach 모드로 실행
ssh user@prod-gpu-server "cd tube-scout && nohup tube-scout collect process-audio --channel nursing --preset prod-a6000-pool --all-takeout > logs/asr-$(date +%Y%m%d).log 2>&1 &"

# 로그 모니터링
ssh user@prod-gpu-server "tail -f tube-scout/logs/asr-*.log"
# [transcripts] video_id=... N=12/2555 elapsed=145s ETA=27345s
```

---

## 7. boundary 부재 검증 (Constitution VII B-11)

본 spec은 spec 008 admin web UI에 변경을 주지 않는다. 운영자가 admin web에서 `ambiguous-mapping 큐` 또는 `Layer D 화이트리스트` UI를 찾으면 부재 — 본 spec은 CLI + CSV 편집 인터페이스만 제공. 향후 web UI 통합은 별도 idea(spec 008 확장)로 분리.

검증:

```bash
# admin web을 실행해도 takeout / asr 메뉴는 없음
tube-scout web start &
curl http://localhost:8000/  # 메뉴 목록에 takeout/asr 항목 0건
```

---

## 8. 디버깅 체크리스트

| 증상 | 점검 |
|---|---|
| `collect takeout` 이 거절 | alias 등록 확인 (`tube-scout admin channel list`) |
| 매핑 자동화율 낮음 | `_ambiguous_mappings.csv` 검토, `_manual_mappings.csv` 보강 |
| WAV 추출 실패 | ffmpeg 설치 확인 (`which ffmpeg`), mp4 파일 무결성 (`ffprobe <path>`) |
| 지문 산출 실패 | chromaprint 설치 확인 (`which fpcalc`) + LD_LIBRARY_PATH (devShell shellHook이 자동 처리) |
| ASR ImportError | `uv sync --extra asr` |
| ASR CUDA OOM | `--compute-type int8` 또는 `--preset cpu-fallback` |
| ASR 환각 빈발 | `asr_quality_flags.hallucination_repeat` 확인, `--no-vad-filter` 시도하지 말 것 (방어 무력화) |
| 분석 중단 → 재실행 진행 0 | `--resume` 사용 (pair_checkpoint 활용) |
| 보고서 PDF 실패 | `uv sync --extra pdf` (weasyprint) |
| KB export 빈 파일 | 자막 segments 0개 — audit `kb_export_audit.csv` reason="empty_transcript" 확인 |

---

## 9. 측정 항목 (운영자가 commit해야 할 후속 데이터)

Phase 1·2·3 진행 중 운영자가 측정 후 spec follow-up amendment에 commit:

| 항목 | 시점 | 파일 위치 |
|---|---|---|
| Evidence Score 가중치/임계 튜닝 | Phase 1 (9-video) | `_workspace/measurement/evidence_score_phase1.md` |
| `fingerprint_input_policy` 기본값 | Phase 1 | `_workspace/measurement/fingerprint_policy_phase1.md` |
| Hallucination 잔여율 | Phase 2 | `_workspace/measurement/hallucination_baseline_phase2.md` |
| ASR throughput PoC GPU | Phase 2 | `_workspace/measurement/asr_throughput_phase2.md` |
| ASR throughput prod GPU pool | Phase 2 | `_workspace/measurement/asr_throughput_prod_phase2.md` |
| nC2 분석 wall-clock | Phase 3 | `_workspace/measurement/nc2_runtime_phase3.md` |
| Audio fp hamming 임계 (re-recorded) | Phase 3 | `_workspace/measurement/audio_fp_threshold_phase3.md` |
| Aggregate score 가중치 공식 | Phase 3 +30일 | spec follow-up amendment |
