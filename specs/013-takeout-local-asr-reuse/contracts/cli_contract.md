# Contract: CLI (Typer 신규 + 확장 명령)

**Module**: `src/tube_scout/cli/` — `collect.py`, `analyze.py` (신규 subcommand 영역), `report.py`, `transcript.py` (신규 분리 후보 또는 `project.py` 확장)
**Boundary**: Constitution IV CLI-First. 모든 명령은 service-layer 함수의 thin wrapper.
**Spec FR mapping**: 본 contract가 cover하는 FR — FR-001/FR-005/FR-006/FR-009 (takeout), FR-010~FR-012 (audio-extract), FR-013~FR-015 (fingerprint), FR-016~FR-022 (transcripts ASR), FR-024~FR-025 (normalize), FR-028~FR-034 (analyze), FR-035~FR-039 (report), FR-040~FR-042 (kb export).

---

## 1. `tube-scout collect takeout`

Takeout export 디렉터리를 입력으로 받아 channel_metadata + video_metadata + mp4 ↔ video_id 매핑을 SQLite + JSON 이중 적재.

```
tube-scout collect takeout
    --takeout-dir <path>            # Takeout 압축 해제 루트 (필수)
    --channel <alias>               # spec 003 alias (필수, 미등록 시 거절)
    [--copy]                        # 기본 심볼릭 링크 / --copy 시 mp4 물리 복사
    [--dry-run]                     # 매핑 결과만 출력, DB write 0
```

**Pre-conditions**: `--channel` 이 spec 003 alias resolver에 등록되어 있음. `--takeout-dir/Takeout/YouTube 및 YouTube Music/` 디렉터리 존재.

**Post-conditions** (성공 시):
- `channel_metadata` row 1개 + `video_metadata` row N개(metadata CSV의 unique video_id 수).
- `<channel_work_dir>/channel_meta.json` + `videos_meta.json` atomic write.
- `<channel_work_dir>/videos/` 하위에 mp4 심볼릭 링크 또는 복사본(매핑 high/medium만).
- ambiguous 케이스는 `01_collect/_ambiguous_mappings.csv` 에 추가.
- audit: `01_collect/takeout_ingest_audit.csv` 에 N+M row(N=video_id, M=ignored CSV 카테고리).

**Exit codes**: 0=성공, 2=alias 미등록, 3=takeout-dir 경로 오류, 4=DB migration 실패.

**Acceptance scenarios (spec.md AS)**:
- AS-P1.1, AS-P1.2 (멱등 재실행), AS-P1.3 (운영자 ambiguous 해결 후 재실행 반영).

---

## 2. `tube-scout collect audio-extract`

mp4 → 16 kHz mono PCM WAV 분리 모드 추출. 캐시 누적.

```
tube-scout collect audio-extract
    --channel <alias>                    # 필수
    [--video-ids <comma-separated>]      # 특정 영상만
    [--all-takeout]                      # video_metadata 전체
    [--audio-cache-dir <path>]           # 기본 /tmp/tube-scout-audio/
    [--keep-audio]                       # 추출 후 삭제 금지 (분리 모드 기본은 캐시 누적이라 무의미하지만 통합 모드와 옵션 통일)
    [--sample-rate 16000]                # 기본 16000
    [--codec pcm_s16le | flac]           # 기본 pcm_s16le
    [--force]                            # 기존 wav 덮어쓰기
```

**Pre-conditions**: `video_metadata.mp4_relative_path` 가 채워진 row 존재.

**Post-conditions**: `<audio_cache_dir>/<video_id>.wav` 생성, audit `audio_extract_audit.csv` row 추가.

**Exit codes**: 0, 2(alias 미등록), 5(ffmpeg 실패 → audit "audio_decode_failed" 후 다음 영상 진행, 최종 1건 이상 실패 시 5).

---

## 3. `tube-scout collect fingerprint --source local`

로컬 mp4 또는 wav에서 chromaprint 지문 추출. spec 012 `extract_chromaprint_fingerprint` 재사용.

```
tube-scout collect fingerprint
    --source local                       # spec 012 호환을 위해 명시 (yt-dlp 흐름과 분기)
    --channel <alias>                    # 필수
    [--video-ids <comma-separated>]
    [--all-takeout]
    [--input-kind mp4 | wav_16k | wav_22k]  # fingerprint_input_policy 명시 (Phase 1 측정 후 default commit)
    [--force]                            # 이미 지문 있어도 재산출
```

**Pre-conditions**: input-kind=mp4면 `video_metadata.mp4_relative_path` 존재. input-kind=wav_16k면 `<audio_cache_dir>/<video_id>.wav` 존재.

**Post-conditions**: `audio_fingerprint` 테이블 row 추가/갱신, audit `fingerprint_audit.csv` row 추가.

---

## 4. `tube-scout collect transcripts --source asr`

faster-whisper로 ASR 자막 생성. hallucination 방어 4종 기본 강제.

```
tube-scout collect transcripts
    --source asr                                              # 본 spec 신규 분기
    --channel <alias>
    [--video-ids <comma-separated>]
    --preset poc-laptop | prod-a6000 | prod-a6000-pool | cpu-fallback   # 필수 (선택 1)
    [--model tiny | base | small | medium | large-v3]
    [--compute-type float32 | float16 | int8_float16 | int8]
    [--device cuda:0 | cuda:1 | cpu]
    [--language ko | en | auto]                              # 기본 ko
    [--beam-size <int>]                                      # 기본 5
    [--vad-filter / --no-vad-filter]                         # 기본 on (FR-017)
    [--retry-failed]                                         # asr_failed row 재시도
    [--cleanup-audio]                                        # 본 영상 처리 후 wav 캐시 삭제
    [--auto-normalize / --no-auto-normalize]                 # 기본 on (FR-025)
```

**Worker pool 진입 (`--preset prod-a6000-pool`)**: 두 프로세스 spawn, 각각 `CUDA_VISIBLE_DEVICES=0` / `=1`. SQLite atomic claim 패턴 (E-8).

**Pre-conditions**: `<audio_cache_dir>/<video_id>.wav` 존재(분리 모드 시) 또는 통합 모드 진입 시 추출 자동 수행.

**Post-conditions**: `01_collect/transcripts/<video_id>.json` atomic write, `processing_status.caption_source='whisper'` + `caption_source_detail='asr:faster-whisper:<size>:<compute_type>'`, `quality_results.asr_quality_flags` JSON 갱신, audit `transcripts_audit.csv` row.

**Edge case**: 모델 캐시 미존재 시 최초 자동 다운로드(B-13). actionable 메시지("Downloading model 'large-v3' to ~/.cache/huggingface/... (~1.5 GB int8 quantized)").

---

## 5. `tube-scout collect process-audio`

통합 파이프라인 — 영상별 [WAV 추출 → 지문 → STT → 정규화 → WAV 삭제] 루프.

```
tube-scout collect process-audio
    --channel <alias>
    [--video-ids <comma-separated>] [--all-takeout]
    --preset poc-laptop | prod-a6000 | prod-a6000-pool | cpu-fallback
    [--skip-fingerprint]                  # 지문 단계 건너뜀
    [--skip-asr]                          # STT 단계 건너뜀
    [--keep-audio]                        # WAV 삭제 금지 (기본은 영상별 즉시 삭제)
    [--retry-failed]
    [--auto-normalize / --no-auto-normalize]
```

**Lifecycle (C-1)**: 영상 1개당 try/finally 블록 — WAV 추출 → 지문 → STT → 정규화 → finally 절에서 WAV 삭제 (`--keep-audio` 미지정 시).

**Signal handling**: SIGINT/SIGTERM 수신 시 현재 영상의 WAV 삭제 후 종료 (audit "interrupted").

---

## 6. `tube-scout process normalize-transcripts`

Text Normalizer 단독 멱등 명령.

```
tube-scout process normalize-transcripts
    --channel <alias>
    [--video-ids <comma-separated>]
    [--force]                              # 기존 transcripts_normalized/ 덮어쓰기
```

**Pre-conditions**: `01_collect/transcripts/<video_id>.json` 존재.

**Post-conditions**: `01_collect/transcripts_normalized/<video_id>.json` atomic write, audit `normalize_audit.csv` row.

**Single-source rule (FR-024)**: 같은 video_id에 ASR과 API caption raw가 동시 존재하면 actionable 영문 메시지("Conflict: video_id=<id> has both ASR ('whisper') and API caption sources. Single-source rule requires operator decision. Remove one of: <path1>, <path2>.") 후 종료(exit 6).

---

## 7. `tube-scout analyze content-reuse`

M-nC2 분석 실행. 보고서와 분리된 명시 단계(FR-033).

```
tube-scout analyze content-reuse
    --channel <alias>
    --professor <name>                     # 필수 (한 교수 단위)
    --mode M-nC2 | M-default               # 기본 M-default (spec 007 호환), 본 spec 신규 M-nC2
    [--layer-a-seconds <float>]            # Layer A 길이 임계
    [--layer-b-threshold <float>]          # Layer B 교수 baseline 임계 (기본 0.30)
    [--resume]                             # pair_checkpoint 이어붙기
    [--force]                              # 기존 comparison_results 덮어쓰기
```

**Pre-conditions**: `transcripts_normalized/` 가 분석 대상 영상에 모두 존재. `processing_status.status='collected' OR 'fingerprinted'`.

**Post-conditions**: `comparison_results` row(쌍 개수만큼) + `match_spans` row + audit `analyze_audit.csv`.

**Atomic resume**: `pair_checkpoint` 테이블 활용 — 동일 (professor, mode, layer_a_seconds, layer_b_threshold) 조합의 미완 분석은 자동 이어붙기.

---

## 8. `tube-scout report content-reuse`

영속된 분석 결과를 PDF/HTML 보고서로 렌더링. 분석을 암묵 실행하지 않음(FR-033).

```
tube-scout report content-reuse
    --channel <alias>
    --professor <name>
    --mode M-nC2 | M-default
    [--top-k <int>]                                       # 기본 50
    [--sort-by i2-cosine | i6-longest-contiguous | i7-distribution-dispersion | i8-position-diversity | audio-fp-hamming]   # 기본 i2-cosine (C-3 deferred)
    [--appendix-threshold-i2-cosine <float>]              # Phase 3 출시 시점 per-metric (C-3)
    [--appendix-threshold-i6-longest-contiguous <float>]
    [--appendix-threshold-i7-distribution-dispersion <float>]
    [--appendix-threshold-i8-position-diversity <float>]
    [--appendix-threshold-audio-fp-hamming <int>]
    [--format pdf | html | both]                          # 기본 both
    [--output <path>]                                     # 기본 projects/{job-id}/03_report/<professor>_nC2_report.{html,pdf}
```

**Pre-conditions**: `comparison_results` 에 (professor, mode) 조합 row 존재.

**Post-conditions**: HTML + PDF 파일 생성, audit `report_audit.csv` row.

**Report tone enforcement (FR-037)**: jinja2 템플릿이 단정적 라벨 어휘를 사용하지 않음. 운영자가 템플릿 override 시 SC-007 회귀 테스트가 검출.

---

## 9. `tube-scout transcript export` / `export-bulk`

KB 입력용 자막 텍스트 export. 단순 변환, 분석 파이프와 무관.

```
tube-scout transcript export
    --video-id <id>
    [--format txt | md | jsonl]            # 기본 txt
    [--keep-timestamps]                    # 기본 off
    [--clean-fillers]                      # ASR 채움 표현 제거
    [--output <path>]                      # 기본 ./kb_export/<video_id>.<format>
    [--with-meta]                          # md/jsonl 시 영상 메타 헤더 포함

tube-scout transcript export-bulk
    --channel <alias>
    [--video-ids-file <txt>]               # 한 줄에 한 video_id
    [--all]                                # 채널 전체
    [--format txt | md | jsonl]
    [--output-dir <dir>]                   # 기본 ./kb_export/<alias>/
    [--keep-timestamps] [--clean-fillers] [--with-meta]
```

**Pre-conditions**: `01_collect/transcripts/<video_id>.json` 존재.

**Post-conditions**: 출력 파일 N개, audit `kb_export_audit.csv` row.

---

## 환경변수

| 변수 | 용도 | 기본값 |
|---|---|---|
| `TUBE_SCOUT_AUDIO_CACHE_DIR` | `--audio-cache-dir` 기본값 override | `/tmp/tube-scout-audio/` |
| `HF_HOME` | faster-whisper 모델 캐시 | `~/.cache/huggingface/` |
| `CUDA_VISIBLE_DEVICES` | 워커 프로세스가 본 spec 내부에서 spawn 시 설정 (운영자 미설정) | (워커별 0 또는 1) |

운영자가 직접 export하는 환경변수는 본 spec 신규 0건(`HF_HOME`은 huggingface 표준, `CUDA_VISIBLE_DEVICES`는 본 spec이 내부에서 설정).

---

## 진행 표시 (C-4)

모든 장시간 명령(`collect process-audio`, `collect transcripts`, `analyze content-reuse`, `report content-reuse`, `transcript export-bulk`)은 `services/progress_reporter.py` 사용. TTY=rich.progress, 비-TTY=structured log line(매 영상 또는 매 N쌍).

---

## CLI 동작 요약

| 명령 | Phase | 신규? | 보고서 출처 |
|---|---|---|---|
| `collect takeout` | 1 | 신규 | takeout_ingest_audit.csv |
| `collect audio-extract` | 1 | 신규 | audio_extract_audit.csv |
| `collect fingerprint --source local` | 1 | 분기 (spec 012 명령 확장) | fingerprint_audit.csv |
| `collect transcripts --source asr` | 2 | 분기 (spec 010/012 명령 확장) | transcripts_audit.csv |
| `collect process-audio` | 2 | 신규 | audio_extract + transcripts + fingerprint + normalize audit |
| `process normalize-transcripts` | 2 | 신규 | normalize_audit.csv |
| `analyze content-reuse` | 3 | 신규 (또는 기존 `content compare/scan`에 `--mode M-nC2` 추가) | analyze_audit.csv |
| `report content-reuse` | 3 | 신규 | report_audit.csv |
| `transcript export` / `export-bulk` | 4 | 신규 | kb_export_audit.csv |
