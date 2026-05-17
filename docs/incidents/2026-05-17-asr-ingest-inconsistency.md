# 2026-05-17 ASR/Ingest 사용성 테스트 인시던트

- **트리거**: 사용자 (kjeong) 가 10개 mp4 (nursing 채널) + 1 박연경 영상 복제본 으로 nC2 비교 검증 시도
- **상태**: 테스트 일시중지. 코드 전수조사 대기.
- **세션 시간**: 2026-05-17 (KST 새벽~오전)
- **근본 이슈 두 갈래**:
  1. 어제(05-16) 22:00 경엔 ASR 가 성공해 transcripts JSON 9개를 만들었는데, 오늘 동일 환경 의도로 재실행 시 모두 실패. **환경 일관성이 보장되지 않음.**
  2. 본 세션 중 flake.nix 에 sqlite 한 줄을 추가하면서, 같은 파일의 GPU shell 이 ctranslate2 4.7.1 의존성 전부 (cuBLAS, cudart 등) 를 link 하는지 검토하지 않음. **수정 단위가 일관성 점검 단위와 불일치.**

---

## 1. Timeline (오늘 발생한 오류 시퀀스)

### 1.1 시작 상태 (05-16 22:00 시점, 어제 마지막 성공)
- `./data/nursing/02_analyze/transcripts/*.json` 9개 존재
- 메타: `source: "asr:faster-whisper:large-v3:int8_float16"`, segments 수십~수백
- 파일 mtime 2026-05-16 21:59~22:11 → **이 시점 환경에서 GPU ASR 가 성공한 사실 확정**
- audit (`ingest_orchestrator_audit.csv`): 12:00~12:01 `asr_fail` → 12:20~ `asr_transcribed` (success)

### 1.2 오늘 (05-17) 의 실패 시퀀스

| # | 시각 (KST) | 명령/이벤트 | 결과 | 진단 |
|---|---|---|---|---|
| ERR-1 | 10:21 경 | `tube-scout collect ingest --preset gpu-quantized` (1차) | 자막 0/9 처리, idempotency 로 9건 `already_transcribed` skip | 정상. 어제 결과 살아있음 |
| OBS-1 | 11:30 경 | sqlite3 CLI 미존재 발견 (`command not found`) | nix devShell 에 sqlite 패키지 부재 | flake.nix 수정으로 해결 |
| ACT-1 | 11:35 경 | flake.nix `commonBuildInputs` 에 `sqlite` 추가 (assistant 수정) | 수정만 됨. 셸 재진입 필요 | **갭**: 같은 파일의 GPU shell deps 점검 없이 단일 라인 추가 |
| ACT-2 | 11:40 경 | `mv ./data/content_reuse.db ./data/...bak_$STAMP`, `mv ./data/nursing ./data/nursing.bak_$STAMP` | 백업 성공 | 사용자 수행. 어제 transcripts 도 같이 백업으로 이동 |
| ACT-3 | 11:42 경 | `data/.../동영상(99).csv` 작성 (DUPTEST00001 fake row) | CSV 생성 | assistant 수행 |
| ERR-2 | 11:42 경 | ingest 재실행 (2차) | 적재 2555 OK, mp4 매핑 10 high OK, **자막 0 처리 / 10 실패**, 음원지문 10 성공 | retry_pending.json: `faster-whisper is not installed` |
| DIAG-1 | 11:50 경 | `which tube-scout` 추적 | `/home/kjeong/.local/bin/tube-scout` → `/home/kjeong/.local/share/uv/tools/tube-scout/bin/python3` 의 isolated venv | uv tool venv 에 `[asr]` 미설치 |
| OBS-2 | 동시 | `uv run python -c "import faster_whisper"` → OK | 프로젝트 .venv 에는 깔려있음 | **두 환경 불일치** |
| ACT-4 | 11:50 경 | `uv tool install --reinstall --editable '.[asr]'` (사용자 수행, 추정) | tool venv 에 faster_whisper 들어옴 | 확정: `/home/kjeong/.local/share/uv/tools/tube-scout/bin/python3 -c "from faster_whisper import WhisperModel"` OK |
| OBS-3 | 동시 | `.envrc.local` 의 `use flake .#gpu` 가 적용 안 됨 발견 | direnv 기본은 `.envrc` 만 source, `.envrc.local` 자동 로드 안 함 | |
| ACT-5 | 11:53 경 | `.envrc` 에 `source_env_if_exists .envrc.local` 추가 + `.gitignore` 에 `.envrc.local` 추가 (assistant 수정) | direnv 표준 패턴 적용 | 사용자 수행: `direnv reload` |
| ERR-3 | 11:54 경 | ingest 재실행 (3차) | `Path error: Neither './Takeout/...' nor './YouTube...' exists` | `direnv reload` 가 환경 reset → 사용자가 직접 export 한 `$TAKEOUT` 소실 |
| ACT-6 | 11:55 경 | `export TAKEOUT=...` 후 ingest 재실행 (4차) | 적재/매핑 OK, **자막 0 처리 / 10 실패, 59.3s** | 모델 로딩 시점까지 갔다가 깨짐 |
| ROOT-CAUSE | 11:56 경 | `retry_pending.json` 실제 사유 확인 | **`faster-whisper transcription failed: Library libcublas.so.12 is not found or cannot be loaded`** | nix GPU shell 이 cuDNN+NVRTC 만 link, **cuBLAS 빠짐** |

### 1.3 어제 (05-16) 대비 오늘 차이 — 어디서 깨졌는가
- 어제 22:00 transcripts JSON 은 진짜 ASR 결과로 확정
- 어제 audit 도 12:20 부터 `asr_transcribed` success — **어제 어느 시점에 cuBLAS 가 어딘가에서 잡혔다는 증거**
- 가능 가설:
  - (G1) 어제 사용자 셸에 시스템 cuBLAS (`/usr/lib/cuda/...` 등) 가 LD_LIBRARY_PATH 또는 ld.so.cache 에서 잡혔고, 셸 재진입 후 그 경로가 빠짐
  - (G2) 어제 사용한 nix profile 이 오늘과 다른 commit (다른 cudaPackages 버전) 이었고, 그쪽엔 cuBLAS 가 transitive 로 들어와 있었음
  - (G3) 어제는 `large-v3` 가 아닌 다른 모델/preset 으로 우회 (그러나 transcripts JSON 의 source 가 `large-v3:int8_float16` 이라 부인됨)
- **검증되지 않은 가설들 — 코드 전수조사에서 확정 필요**

---

## 2. 본 세션에 적용된 코드/설정 변경 (현재 워크트리)

| 파일 | 변경 내용 | 검증 상태 |
|---|---|---|
| `flake.nix` | `commonBuildInputs` 에 `sqlite` 추가 (line 60~) | sqlite CLI 확보. **GPU shell cudaPackages 완결성은 점검 안 됨** |
| `.envrc` | `source_env_if_exists .envrc.local` 추가 | direnv 표준 패턴. 검증됨 |
| `.gitignore` | `.envrc.local` 추가 | 검증됨 |
| `.envrc.local` (사용자 신규) | `use flake .#gpu` | 검증됨 |
| `data/takeout-.../동영상 메타데이터/동영상(99).csv` (assistant 신규) | DUPTEST00001 fake row 한 줄 | CSV ingest 매핑 의도대로 동작 (10 high). 테스트 시나리오 종료 시 삭제 필요 |
| `data/takeout-.../동영상/42- 2. … 7주차 …mp4` (사용자 신규) | 6주차 mp4 의 cp 복제본 | sha256/size 동일 확인됨 |
| `data/content_reuse.db.bak_20260517_114016` | 어제 DB 백업 | 보존 |
| `data/nursing.bak_20260517_114016/` | 어제 work_dir 백업 (transcripts 9개 포함) | 보존 — 어제 ASR 결과의 원본 사실 증거 |

---

## 3. 코드 전수조사 필요 항목 (assistant 가 자체 식별한 일관성 갭)

다음 항목들을 **연관 그룹** 으로 묶어서 한 번에 점검해야 함. 각 항목이 깨지면 본 인시던트와 유사한 환경 재현 실패가 다시 발생함.

### 3.1 ASR 환경 의존성 매트릭스 일관성
- **G-1**: `flake.nix` `devShells.gpu` 의 `cudaPackages` 가 ctranslate2 4.7.1 의존성 전부 (cuDNN + NVRTC + **cuBLAS** + cuRAND + cudart) 를 link 하는가?
- **G-2**: `pyproject.toml` 의 `[asr]` extra 가 핀하는 `faster-whisper` / `ctranslate2` 버전이 (G-1) 의 cudaPackages 버전과 호환되는가?
- **G-3**: `flake.nix` 와 `pyproject.toml` 변경 시 어느 한쪽이 추가로 손이 안 가도 되는지 명시한 문서 (CLAUDE.md / docs) 가 있는가? 없다면 신설 필요.

#### 감사 결과 (audit_consistency_20260517_g_d_c.md)

- **G-1.a** (재발 위험도: High) — cuBLAS / cuda_cudart absent from devShells.gpu buildInputs *(G-4 binary analysis 정정: cuRAND 불필요)*
  - 증거: `flake.nix:101-104` — `devShells.gpu.buildInputs` 에 `cudaPackages.libcublas`, `cuda_cudart` 부재. G-4 binary analysis 확정(nixpkgs rev 8110df5, CUDA 12.9): ctranslate2 4.7.1 이 실제 dlopen 하는 대상은 `libcublas.so.12` + `libcuda.so.1` **2개뿐**. cuRAND 는 dlopen 대상 아님.
  - 현재 동작: CTranslate2 4.x 가 dlopen 으로 `libcublas.so.12` 를 요구하지만 GPU shell 의 LD_LIBRARY_PATH 에 없어 `Library libcublas.so.12 is not found` 즉시 사망. 기대 동작: buildInputs 에 `libcublas` (libcublas.so.12) + `cuda_cudart` (libcuda.so.1) 추가.
  - 수정 권고: `cudaPackages.libcublas cudaPackages.cuda_cudart` 를 `devShells.gpu` buildInputs 에 추가. cuRAND 는 추가 불필요.

- **G-1.b** (재발 위험도: High) — GPU shellHook LD_LIBRARY_PATH 에 cuBLAS/cudart lib 경로 누락
  - 증거: `flake.nix:106-109` — shellHook 이 `cudnn/lib` + `cuda_nvrtc/lib` 만 export; libcublas/libcuda 경로 없음
  - 현재 동작: buildInputs 에 패키지를 추가해도 nix mkShell 은 unfree 패키지의 `/lib` 를 LD_LIBRARY_PATH 에 자동 노출하지 않아 dlopen 실패 지속. 기대 동작: 각 CUDA 패키지의 `/lib` 경로를 shellHook 에서 명시적으로 append.
  - 수정 권고: G-1.a 와 함께 shellHook 에 `${pkgsUnfree.cudaPackages.libcublas}/lib:${pkgsUnfree.cudaPackages.cuda_cudart}/lib` 추가.

- **G-1.c** (재발 위험도: Medium) — GPU lib 경로를 집중할 gpuLibPath 헬퍼 변수 부재
  - 증거: `flake.nix:68-76` — `commonLibPath` 는 WeasyPrint 용; GPU CUDA 경로는 shellHook 에 개별 나열
  - 현재 동작: GPU 의존성 추가 시마다 두 곳(buildInputs + shellHook) 을 동시에 수정해야 해서 누락 발생. 기대 동작: `gpuLibPath = pkgs.lib.makeLibraryPath (...)` 변수 하나에서 집중 관리.
  - 수정 권고: `let` 블록에 `gpuLibPath` 변수 신설.

- **G-2.a** (재발 위험도: Medium) — pyproject.toml `[asr]` extra 가 ctranslate2 버전을 직접 핀하지 않음
  - 증거: `pyproject.toml:80-82` — `faster-whisper>=1.0.0,<2.0.0` 만 선언; ctranslate2 는 transitive dep
  - 현재 동작: uv 가 ctranslate2 임의 버전을 resolve 할 수 있어 CUDA ABI 매트릭스와 무결성 보장 불가. 기대 동작: `ctranslate2>=4.7.0,<5.0.0` 명시 + CUDA 12.x 기준 주석.
  - 수정 권고: `[asr]` extra 에 `ctranslate2>=4.7.0,<5.0.0` 추가.

- **G-2.b** (재발 위험도: Medium) — nixpkgs `nixos-unstable` 로 float (CUDA 버전 미고정)
  - 증거: `flake.nix:5` — `nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable"`
  - 현재 동작: `nix flake update` 시 CUDA 런타임 버전이 무음으로 바뀔 수 있어, 검증된 ctranslate2/cuBLAS ABI 가 다음 업데이트에서 깨질 가능성. 기대 동작: 검증된 nixpkgs 커밋을 고정.
  - 수정 권고: 검증된 nixpkgs rev 로 URL 고정 또는 `docs/quickstart.md` GPU 섹션에 `nix flake metadata` 확인 절차 명시.

- **G-3.a** (재발 위험도: Low) — pyproject extras 와 Nix system deps 간 cross-reference 주석 없음
  - 증거: `flake.nix:54-56` — chromaprint/ffmpeg 주석이 spec 013 을 참조하나 pyproject extra 이름 미언급
  - 현재 동작: 어느 Nix 패키지가 어느 pyproject extra 에 대응하는지 코드에서 추적 불가. 기대 동작: `commonBuildInputs` 근방에 `# [pdf]`, `# [asr]` 등 extra 대응 주석 추가.
  - 수정 권고: `flake.nix` 에 inline extra-대응 주석 블록 추가.

### 3.2 진입점 (CLI) 환경 일관성
- **E-1**: `tube-scout` CLI 가 `uv tool` isolated venv 와 프로젝트 `.venv` 중 어느 쪽을 권위로 보는지 — 두 곳 모두에서 같은 extra 가 보장되는가?
- **E-2**: `uv tool install` 시 extra 가 누락되는 사고를 막는 가드 (예: pre-flight check, doctor 명령) 가 있는가?
- **E-3**: lazy import 실패 메시지 (`faster-whisper is not installed`) 가 ImportError 외 사유(cuBLAS missing 등) 까지 같은 문자열로 catch 하는지 — false attribution 가능성. `src/tube_scout/services/asr.py` 의 except 블록 검토.

#### 감사 결과 (src/ spot-check)

- **E-1.a** (재발 위험도: High) — uv tool isolated venv 와 프로젝트 .venv 간 extra 동기화 보장 없음
  - 증거: `DIAG-1` — `which tube-scout` → `/home/kjeong/.local/bin/tube-scout` (uv tool venv); `uv run python -c "import faster_whisper"` → OK (프로젝트 .venv). 두 환경이 독립적으로 존재하며 extra 동기화 메커니즘 없음.
  - 현재 동작: `uv tool install tube-scout` 로 설치 시 `[asr]` extra 가 누락되어 `faster-whisper is not installed` 오류 발생. 프로젝트 .venv 에는 설치되어 있어도 tool venv 에 반영 안 됨. 기대 동작: 운영 진입점을 `uv run tube-scout` 로 단일화하거나, tool 설치 권장 명령에 extra 를 명시.
  - 수정 권고: `docs/quickstart.md` 에 "운영용 CLI 설치: `uv tool install --editable '.[asr]'`" 를 명시. uv run 방식도 병기.

- **E-2.a** (재발 위험도: High) — 실행 전 환경 검증 명령(doctor) 부재
  - 증거: 코드베이스 전체에 `tube-scout doctor` 또는 `tube-scout env-check` 에 해당하는 CLI 명령 없음. `D-1.b` 와 교차.
  - 현재 동작: 사용자는 `which tube-scout`, `python -c "from faster_whisper import WhisperModel"`, `echo $LD_LIBRARY_PATH | tr : '\n' | grep cuda` 를 수동으로 확인해야 하며, 문서화도 없음. 기대 동작: `tube-scout doctor` 명령이 active Python path, devShell variant, faster_whisper 임포트 가능 여부, CUDA 라이브러리 경로를 한 번에 출력.
  - 수정 권고: 우선은 `docs/quickstart.md` 에 수동 검증 3단계 명시. 정식 `doctor` 명령 신설은 별도 spec.

- **E-3.a** (재발 위험도: High, **정정됨**) — asr.py outer except 가 cuBLAS OSError 를 RuntimeError 로 래핑; ImportError catch 자체는 OK
  - 증거: `src/tube_scout/services/asr.py:562-564` — `except Exception as exc: raise RuntimeError(f"faster-whisper transcription failed: {exc}")` — cuBLAS dlopen RuntimeError 가 이 경로로 전파됨. *(ADV-2 검증: `_load_model` 의 except ImportError 는 순수 Python import 실패만 잡음 — cuBLAS OSError 흡수 가설은 부정됨. outer except 래핑이 실재하지만 false-attribution 의 핵심 원인은 ADV-1 의 audit reason collapse.)*
  - 현재 동작: `retry_pending.json` 의 failure_reason 에 `"faster-whisper transcription failed: Library libcublas.so.12 is not found..."` 로 기록되어 cuBLAS-missing vs 패키지 미설치 구별이 어려움. **진짜 false-attribution 근원은 ADV-1** (unified_ingest.py audit reason 단일 토큰 collapse — 별도 finding). 기대 동작: CUDA lib missing 실패 시 별도 힌트 출력.
  - 수정 권고: `asr.py:562-564` 에서 CUDA lib missing 키워드 (`libcublas`, `libcudart`, `libcublasLt`, `is not found or cannot be loaded`, `ctranslate2`) 감지 시 분류 메시지 출력. `"cuda"` 광역 키워드는 OOM 오진 위험으로 제외.

- **ADV-1** (재발 위험도: High, **권위 finding 승격**) — unified_ingest.py 3-way audit reason collapse → false attribution 핵심
  - 증거: `src/tube_scout/services/unified_ingest.py:269/316/361` — 3개 except 블록이 모든 실패 사유를 `asr_fail` / `fp_fail` / `audio_decode_failed` 단일 토큰으로만 audit CSV 에 기록. cuBLAS-missing, OOM, 패키지 미설치, 네트워크 오류, disk full 이 모두 동일 `asr_fail` 토큰으로 collapse.
  - 현재 동작: 운영 대시보드에서 cuBLAS-missing vs OOM vs 패키지 미설치 구분 불가 → 본 인시던트에서 30분 이상 진단 지연의 직접 원인. 기대 동작: audit CSV 에 `sub_reason` 또는 `error_class` 컬럼 추가 — `ImportError` / `RuntimeError:cuBLAS` / `OSError:disk-full` / `RuntimeError:fpcalc` 등으로 분류.
  - cascade 효과: ADV-1 fix 1건으로 ADV-2(ImportError vs RuntimeError 혼동), ADV-16(네트워크 끊김), ADV-17(disk full), ADV-19(truncated mp4) 5건 동시 해소.

### 3.3 idempotency 와 환경 변화의 상호작용
- **I-1**: spec 018 의 `already_transcribed` skip 정책이 "이전 환경에서 만들어진 transcripts JSON" 을 어떤 metadata 기준으로 신뢰하는가? (예: source 필드의 model_version 확인 없음)
- **I-2**: 어제 환경과 오늘 환경이 다를 때 (예: cuda 버전, 모델) 자동 invalidation 메커니즘 부재 — 정책 결정 필요
- **I-3**: 사용자가 `mv data/nursing` 백업 했을 때 retry_pending.json / transcripts / audit 가 일관되게 모두 같이 이동하는가? (오늘 사용자 직접 mv 로 OK 했지만, 정식 reset 명령이 없음 — 사용자 수동 mv 의 위험성)

#### 감사 결과 (src/ spot-check)

- **I-1.a** (재발 위험도: High) — already_transcribed skip 이 transcript JSON 의 source 필드 (모델/환경) 를 검증하지 않음
  - 증거: `src/tube_scout/services/unified_ingest.py:148` — `transcript_skip = (transcript_dir / f"{video_id}.json").exists()` — 파일 존재 여부만 확인; source 필드 (`asr:faster-whisper:large-v3:int8_float16`) 및 모델 버전 미검증.
  - 현재 동작: 어제 다른 환경(다른 모델 크기, 다른 compute_type) 에서 생성된 transcript JSON 이 오늘 `already_transcribed` 로 skip 되어 재처리 불가 — `--force` 없이는 환경 변화가 반영 안 됨. 기대 동작: source 필드의 모델/compute_type 이 현재 preset 과 불일치 시 warn 또는 재처리.
  - 수정 권고: `_check_already_processed` 에서 기존 transcript JSON 의 `source` 필드와 현재 `asr_kwargs` 를 비교하는 선택적 model_version_check 추가. (정책 결정 필요: warn-only vs. force-reprocess.)
  - cross-persona 극단 시나리오 (ADV-20 통합): preset 을 `cpu:medium` → `gpu-quantized:large-v3` 로 변경 시 기존 cpu medium 자막이 `already_transcribed` 로 조용히 재사용됨 — 품질 저하가 감사 CSV 에 기록 안 됨.
  - SB-4.a 세부 케이스: cuDNN 업그레이드 후 nix flake update 시 동일 현상 (stale large-v3 transcript 를 새 cuDNN 환경에서 재사용).
  - SB-4.b 세부 케이스: preset gpu→cpu 전환 후 mixed-model transcript pool 생성 — find_match_spans 의 segment boundary 가 모델마다 달라 비교 정확도 저하.

- **I-1.b** (재발 위험도: High) — _check_already_processed 에 expected_caption_source 파라미터 없음
  - 증거: `src/tube_scout/services/unified_ingest.py:119-165` — `_check_already_processed` 시그니처에 현재 preset/model 정보를 받는 파라미터 없어 source 필드 비교 자체가 구조적으로 불가능.
  - 현재 동작: I-1.a 의 source 필드 검증을 구현하려면 함수 시그니처 변경이 필요하나 현재 설계에서 불가. 기대 동작: `expected_caption_source: str | None = None` 파라미터 추가.
  - 수정 권고: OPEN-H 정책 결정 후 함수 시그니처 확장.

- **I-2.a** (재발 위험도: Medium) — 환경 변화(CUDA 버전, nix profile) 에 대한 자동 invalidation 정책 없음
  - 증거: `docs/incidents/2026-05-17-asr-ingest-inconsistency.md §1.3` — 어제 성공/오늘 실패 차이가 환경 변화(cuBLAS LD_LIBRARY_PATH 소실)에 기인. 코드베이스에 nix devShell 버전이나 cuBLAS 가용성을 transcript JSON 에 기록하는 메커니즘 없음.
  - 현재 동작: 환경이 바뀌어도 transcript JSON 이 남아 있으면 `already_transcribed` 로 skip 됨 — 나쁜 transcript 가 조용히 서비스됨. 기대 동작: `--force` 로 수동 우회하거나, transcript JSON 에 nix devShell 해시/CUDA 버전 기록.
  - 수정 권고: 단기 — `docs/quickstart.md` 에 "환경 변경 후 재처리 시 `--force` 필요" 명시. 장기 — transcript JSON 메타에 `env_hash` 필드 추가(spec 레벨 결정).

- **I-3.a** (재발 위험도: Medium) — work_dir 수동 백업 시 retry_pending.json / audit / DB 가 불일치 상태에 빠질 수 있음
  - 증거: `§2` — 사용자가 `mv ./data/nursing ./data/nursing.bak_$STAMP` 수행; retry_pending.json 과 ingest_orchestrator_audit.csv 는 같이 이동됐지만, content_reuse.db (audio_fingerprint 테이블) 는 별도 경로(`data/content_reuse.db`) 에 남아 있어 DB 에는 fingerprint 가 있지만 transcript 는 없는 부분 일관성 상태가 됨.
  - 현재 동작: `mv` 후 ingest 재실행 시 fingerprint_skip=True, transcript_skip=False 로 혼합 처리 — 의도한 "완전 리셋" 이 아님. 기대 동작: work_dir reset 시 DB 레코드도 함께 정리하는 `tube-scout collect reset --channel <alias>` 명령 또는 최소한 reset 절차 문서.
  - 수정 권고: `docs/quickstart.md` 에 수동 reset 절차(mv + sqlite DELETE) 명시. 정식 reset 명령은 별도 spec.

### 3.4 direnv / nix-direnv 캐시 일관성
- **D-1**: `.envrc` 변경 시 사용자가 `direnv reload` 또는 `rm -rf .direnv` 어느 쪽을 해야 하는지 명시되어 있는가? 캐시가 이전 셸 ENV 를 transmit 하는 사고 (오늘 OBS-3) 의 재발 방지
- **D-2**: nix-direnv 가 `cached dev shell` 메시지를 출력했을 때, 실제 envvar 가 갱신됐는지 검증할 doctor 명령 또는 가이드

#### 감사 결과 (audit_consistency_20260517_g_d_c.md)

- **D-1.a** (재발 위험도: High) — direnv reload 절차 및 세션 변수 소실 경고 문서 없음
  - 증거: `docs/quickstart.md`, `CLAUDE.md`, `docs/tutorial.md`, `docs/for-new-teachers.md` — `direnv reload` 또는 `.direnv` 캐시 언급 없음.
  - 현재 동작: `.envrc` 변경 후 `direnv reload` 시 사용자가 직접 export 한 `$TAKEOUT` 등 세션 변수가 소실됨 (ERR-3). 사용자는 이를 예상하지 못함. 기대 동작: `docs/quickstart.md` GPU 섹션에 (1) `direnv allow` + `direnv reload` 순서, (2) reload 후 세션 변수 재export 필요 명시.
  - 수정 권고: `docs/quickstart.md` 에 "GPU / nix-direnv 워크플로우" 서브섹션 신설.

- **D-1.b** (재발 위험도: High) — 활성 devShell variant 검증 명령(doctor) 부재 (E-2.a 와 교차)
  - 증거: codebase 전반에 `tube-scout doctor` 없음. `DIAG-1` 에서 `which tube-scout` 수동 추적으로 간신히 발견.
  - 현재 동작: 사용자는 active shell 이 `default` 인지 `gpu` 인지, faster_whisper 가 로드 가능한지를 수동 점검해야 함. 기대 동작: 단일 명령으로 환경 상태 진단.
  - 수정 권고: `docs/quickstart.md` 에 수동 검증 3단계 (`which tube-scout` / `python -c "from faster_whisper import WhisperModel"` / `echo $LD_LIBRARY_PATH | tr : '\n' | grep cuda`) 명시.

- **D-2.a** (재발 위험도: High) — .envrc.local override 패턴 문서화 없음
  - 증거: `.envrc:8` — `source_env_if_exists .envrc.local` 존재 (ACT-5 추가); `.gitignore:29` — `.envrc.local` gitignore. `docs/quickstart.md` 에 언급 없음.
  - 현재 동작: 신규 기여자는 `.envrc.local` 에 `use flake .#gpu` 를 작성해야 GPU shell 이 direnv 를 통해 활성화되는 사실을 알 방법이 없음. 기대 동작: `docs/quickstart.md` 에 `.envrc.local` 생성 방법과 gitignore 사실 명시.
  - 수정 권고: `docs/quickstart.md` GPU 섹션에 `.envrc.local` 설정 절차 추가.

- **D-3.a** (재발 위험도: Medium) — `nix develop .#gpu` vs direnv 차이 문서화 없음
  - 증거: 어느 문서에도 두 방식의 동작 차이(nested subshell vs 현재 셸 환경 변조, 캐시 동작 차이) 설명 없음.
  - 현재 동작: 사용자가 두 방식을 혼용할 때 예상치 못한 동작(캐시 stale, 세션 변수 소실) 발생. 기대 동작: `docs/quickstart.md` 에 두 방식의 트레이드오프 표 제공.
  - 수정 권고: 2행 비교 표 (`nix develop .#gpu`: 간단, 1회성 / direnv: 편리, 단 reload 후 세션 변수 재export 필요) 추가.

### 3.5 사용자 input 변동성에 대한 robustness
- **R-1**: ingest 명령이 `--takeout-dir ""` (빈 문자열) 을 받았을 때 더 명확한 에러 (현재는 `./Takeout/...` 라는 추정 상대경로로 시도 후 실패) — UX 개선
- **R-2**: CSV fake row 추가가 정식 운영 시나리오인지 임시 우회인지 — 정식 운영이면 별도 CLI (`tube-scout content register-test-video`) 가 있어야 함

#### 감사 결과 (src/ spot-check)

- **R-1.a** (재발 위험도: Medium) — --takeout-dir 미지정 또는 상대경로 처리 시 에러 메시지가 실패 지점 누락
  - 증거: `src/tube_scout/cli/collect.py:2696-2699` — `takeout_path = Path(takeout_dir)` 후 `if not takeout_path.exists()` 로 `"does not exist"` 에러. ERR-3 에서 `direnv reload` 로 `$TAKEOUT` 소실 후 재실행 시 `"Path error: Neither './Takeout/...' nor './YouTube...' exists"` 표시. 상대경로로 해석된 사실이 에러 메시지에 없어 사용자가 원인을 즉시 파악 불가.
  - 현재 동작: `$TAKEOUT` 소실로 빈 문자열이나 상대경로가 전달될 때 에러 메시지에 실제 해석된 절대경로가 출력되지 않아 진단 어려움. 기대 동작: 에러 메시지에 `Path(takeout_dir).resolve()` 결과 포함.
  - 수정 권고: `collect.py:2698` 에러 메시지를 `f"[red]Error: --takeout-dir '{takeout_path.resolve()}' does not exist.[/red]"` 로 변경.

- **R-2.a** (재발 위험도: Low) — CSV fake row 수동 추가가 공식 테스트 시나리오로 문서화되지 않음
  - 증거: `§2` — `data/takeout-.../동영상(99).csv` (assistant 신규, DUPTEST00001 fake row). 공식 `tube-scout` CLI 에 test-video 등록 명령 없음.
  - 현재 동작: 중복 검출 테스트를 위해 CSV 를 직접 편집 — 데이터 오염 위험, 테스트 종료 후 정리 의존성 발생. 기대 동작: 정식 테스트 시나리오 CLI 또는 최소한 fixture 파일 기반 절차.
  - 수정 권고: 단기 — `docs/quickstart.md` 에 "중복 검출 테스트용 CSV 수정 절차 및 정리 의무" 명시. 장기 — `tube-scout content register-test-video` CLI 신설(별도 spec).

- **R-4.a** (재발 위험도: High) — cuBLAS 부재 에러 메시지가 사용자에게 unactionable
  - 증거: ERR-3/ROOT-CAUSE — `retry_pending.json` 에 `"Library libcublas.so.12 is not found or cannot be loaded"` 기록되지만 CLI 종료 시 이 메시지가 콘솔에 출력되지 않음. 사용자는 별도로 retry_pending.json 을 열어야만 확인 가능.
  - 현재 동작: cuBLAS 부재로 인한 실패 시 CLI 가 `"자막 0 처리 / 10 실패"` 만 출력 — root cause 즉시 파악 불가. 기대 동작: 실패 시 failure_reason 상위 N건을 콘솔에 출력.
  - 수정 권고: R-7.a 와 함께 처리 — ingest 종료 시 transcript/fingerprint 실패가 있으면 failure_reason 상위 3건을 콘솔에 출력.

- **R-4.b** (재발 위험도: High) — GPU auto-detect 후 batch 전체 fail, CPU fallback 없음
  - 증거: `src/tube_scout/services/asr.py:248-265` — `resolve_preset` 이 GPU VRAM 기반 auto-detect 로 `gpu-quantized` 선택 후 실제 cuBLAS dlopen 실패 시 batch 전체 실패. CPU fallback 로직 없음. N개 영상 × 60s WAV decode 대기 후 전부 `asr_fail`.
  - 현재 동작: cuBLAS 없는 GPU shell 에서 auto-detect 로 gpu-quantized 선택 → 10개 × ~60s 처리 후 전부 실패 — 사용자가 59.3s 소요 후 결과 0건 확인. 기대 동작: WhisperModel 로드 실패 시 CPU fallback 또는 즉시 batch abort + 명확한 에러.
  - 수정 권고: OPEN-A(flake.nix fix) 가 근본 원인 해소. 추가로 WhisperModel 인스턴스화 전 cuBLAS 가용성 pre-check 또는 batch 첫 영상 실패 시 조기 중단 로직 고려.

- **R-7.a** (재발 위험도: High) — ingest 종료 시 CLI 에 실패 사유 미출력 → ROOT-CAUSE 진단 20분 지연
  - 증거: `src/tube_scout/services/unified_ingest.py:442-508` (`_print_summary_table`) — 실패 건수만 출력; failure_reason 미출력. 사용자가 retry_pending.json 을 수동으로 열어야 함.
  - 현재 동작: `"자막 실패 10"` 만 표시. 사유(cuBLAS-missing)를 확인하려면 `cat retry_pending.json | jq '.entries[0].failure_reason'` 수동 실행 필요. 기대 동작: failure_count > 0 일 때 상위 3건의 failure_reason 을 콘솔에 표시.
  - 수정 권고: `_print_summary_table` 또는 호출부에서 `failures[:3]` 의 failure_reason 을 출력하는 코드 추가 (R-4.a 와 동일 fix).

- **BUX-1** (재발 위험도: High) — 진행률 표시가 mp4 단위 → 오래 걸리는 영상에서 stall 오인 → Ctrl+C 유발
  - 증거: `src/tube_scout/services/unified_ingest.py:216-228` — Progress bar 가 `MofNCompleteColumn` 으로 "mp4 완료 N/M" 표시. 한 영상의 ASR 이 60s 이상 걸릴 때 진행률이 멈춰 보여 stall 오인 발생.
  - 현재 동작: 사용자가 59.3s 진행 중 stall 오인으로 Ctrl+C 시도. SIGINT 핸들러 없어 in-flight 영상이 retry_pending.json 에 기록되지 않을 수 있음 (R-10.a 연계).
  - 수정 권고: Progress bar 에 "현재 영상 경과 시간" 또는 "ASR 진행 중" 스피너 텍스트 추가. TimeElapsedColumn 이 있으나 per-video 경과시간 불표시.

- **R-8.a** (재발 위험도: Medium) — 동일 alias 두 번 ingest 시 INSERT OR IGNORE 로 멱등 동작하나 사용자에게 비가시화
  - 증거: takeout_ingest.py INSERT OR IGNORE 패턴. 두 번 실행 시 DB 레코드 중복 없으나, "이미 있음" 사실이 콘솔에 표시되지 않아 사용자가 재실행 여부를 알 수 없음.
  - 수정 권고: OPEN-D docs 갱신 항목으로 병합. 멱등 동작은 설계 의도 — "skip 된 건수" 출력 추가만으로 충분.

- **R-10.a** (재발 위험도: Medium) — Ctrl+C 후 SIGINT 핸들러 없음 → in-flight video retry_pending 미기록
  - 증거: `src/tube_scout/services/unified_ingest.py` — KeyboardInterrupt 핸들러 없음. Ctrl+C 시 현재 처리 중인 영상이 failures 에도 successes 에도 기록 안 됨 → retry_pending.json 에 누락.
  - 현재 동작: Ctrl+C 후 재실행 시 중단된 영상이 retry_pending 에 없어 재처리 안 됨 — 조용한 데이터 갭.
  - 수정 권고: `_run_transcript_and_fingerprint` 에서 KeyboardInterrupt 를 catch 해 현재까지의 failures 를 retry_pending.json 에 기록 후 재raise.

- **R-12.a** (재발 위험도: Low) — --preset 옵션 help 텍스트에 GPU shell 진입 사전 조건 미언급
  - 증거: `src/tube_scout/cli/collect.py:2634-2645` — `--preset` help 가 preset 이름과 VRAM 임계값은 설명하나 "GPU devShell 진입 필요" 사전 조건 미언급.
  - 수정 권고: F-5(quickstart.md) 에서 커버 — help 텍스트 변경은 별도 우선순위 낮음.

### 3.6 fix → 일관성 점검 의무화
- **C-1**: 본 세션의 sqlite 추가처럼 `flake.nix` 또는 `pyproject.toml` 변경 시 같은 파일의 다른 환경 (default/gpu, lean/asr/pdf) 의 완결성을 함께 점검하는 절차가 CLAUDE.md / contribution guide 에 명시되어 있는가? 없다면 추가 필요 — **이번 사용자 비판의 핵심**

#### 감사 결과 (audit_consistency_20260517_g_d_c.md)

- **C-1.a** (재발 위험도: High) — CLAUDE.md 에 cross-environment 일관성 점검 의무 규칙 없음 (핵심 갭)
  - 증거: `CLAUDE.md` (project) — `flake.nix` 또는 `pyproject.toml` 수정 시 다른 devShell/extra 완결성을 함께 점검하라는 규칙 없음. global `CLAUDE.md §3.3` Surgical Changes 는 "touch only what the request requires" 를 말하나 이는 반대 방향 문제(인접 코드 과잉 수정)를 다룸.
  - 현재 동작: `commonBuildInputs` 에 sqlite 한 줄 추가 시 GPU shell deps 점검 불이행 (ACT-1) — 이번 사용자 비판의 핵심. 기대 동작: `CLAUDE.md` (project) 에 "flake.nix 수정 시 모든 devShell variant(default/gpu) 완결성 검증, pyproject.toml extras 수정 시 대응 Nix 패키지 존재 확인" 규칙 명시.
  - 수정 권고: `CLAUDE.md` (project) 에 "Consistency Invariants" 섹션 신설 (contrib-guide 갱신 필요).

- **C-2.a** (재발 위험도: High) — flake.nix / pyproject.toml co-change 를 잡아주는 pre-commit hook 또는 tooling guard 없음
  - 증거: `.pre-commit-config.yaml` 없음; `pyproject.toml [tool.ruff]` / `[tool.mypy]` 는 flake.nix 미커버. Makefile/justfile 없음.
  - 현재 동작: 개발자가 `commonBuildInputs` 를 변경하면서 GPU-specific 섹션을 검토 안 해도 아무것도 막지 않음. 기대 동작: flake.nix 수정 시 "Did you check both devShells?" 리마인더 또는 `tube-scout doctor` 로 cudaPackages 목록 확인.
  - 수정 권고: 즉각 저비용 가드로 `flake.nix` 의 `devShells.gpu` 바로 위에 CTranslate2 4.x dlopen 요구사항 전체를 열거하는 주석 블록 추가 — 편집 시 시각적 경고 역할.

- **C-3.a** (재발 위험도: Medium) — pyproject extras 변경 시 flake.nix 동시 갱신 의무를 공식화한 규칙 없음
  - 증거: `CLAUDE.md` (project) "Active Technologies" 는 과거 서사; 새 extra 추가 시 flake.nix 갱신 의무를 명시하는 forward-looking 규칙 없음.
  - 현재 동작: spec 013 의 `[asr]` extra 추가 시 chromaprint/ffmpeg/cudnn/cuda_nvrtc 를 flake.nix 에 같이 추가한 것은 관례(convention)에 의한 것이지 강제된 절차가 아님. 기대 동작: CLAUDE.md §11 Self-Check 또는 project Consistency Invariants 섹션에 checklist 항목 명시.
  - 수정 권고: `CLAUDE.md §11` 에 "새 pyproject extra 가 native system dep 를 wrap 한다면 flake.nix buildInputs + shellHook 도 동시 갱신" 체크리스트 항목 추가.

### 3.7 규모 확장 시 병목 및 환경 변화 시나리오 (SB 그룹)

*qa-cross 통합 (2026-05-17): audit_e_i.md SB 그룹 6건 — first-pass 에서 완전 누락.*

**공통 메타패턴**: §3.3/§3.4 의 "invalidation policy absent" 가 규모(2200 영상) 와 환경 변화(cuDNN 업그레이드, preset 전환) 조합 시 더 큰 피해를 낳는 경로.

- **SB-1** (재발 위험도: High) — 2200 영상 → 2.4M pairs, O(n²) full iteration, Layer-A cull 없음
  - 증거: spec 013 path 의 nC2 pair iteration 이 Layer-A upfront cull 없이 전체 pair 를 순회. 현재 22개 채널 × 100 영상 = 2200 videos → C(2200,2) ≈ 2.42M pairs. GPU pool 없이 CPU 단일 실행 시 추정 수십 시간.
  - 현재 동작: 전수 pair 비교 → 실용적 처리 시간 초과. 기대 동작: channel-level 사전 필터(동일 채널 pair 제외, fingerprint distance 하한 컷) 로 pair 수 대폭 감소.
  - 수정 권고: spec 019 가속 진입 조건 확인 (메모리 기록: 진입 조건 2개 만족 여부 사용자 결정). OPEN-I 등록.

- **SB-2** (재발 위험도: Low) — per-process WhisperModel 재로드 (HuggingFace 캐시 ~2.9 GB)
  - 증거: `asr.py:333` — `@functools.lru_cache(maxsize=1)` 로 프로세스 내 싱글톤 유지. 멀티프로세스 실행 시 각 프로세스가 독립 로드. `~/.cache/huggingface/` 가 nix store 밖 — CI/멀티호스트 환경에서 캐시 miss 시 2.9 GB 재다운로드.
  - 수정 권고: 현 단일 프로세스 환경에서는 lru_cache 로 충분. 멀티호스트 시 HF_HOME 공유 마운트 필요 — 별도 인프라 결정.

- **SB-3** (재발 위험도: Medium) — nC2 비교 시 segment boundary mismatch 잠재위험
  - 증거: find_match_spans 가 segment start/end 를 정수 초 단위로 비교. 모델 크기(medium vs large-v3) 에 따라 segment 경계가 달라져 동일 발화를 다른 segment 로 분리할 수 있음.
  - 수정 권고: SB-4.b 정책 결정(모델 버전 통일) 과 연동.

- **SB-4.a** (재발 위험도: High) — cuDNN 업그레이드 후 stale large-v3 transcript 조용히 재사용
  - 증거: I-1.a/I-1.b 의 구체 시나리오. `nix flake update` → cuDNN 버전 변경 → 재실행 시 기존 transcript JSON 이 `already_transcribed` 로 skip — 새 cuDNN 환경에서 재검증 없이 이전 결과를 신뢰.
  - 수정 권고: OPEN-H 정책 결정 후 I-1.a/I-1.b 와 함께 처리.

- **SB-4.b** (재발 위험도: High) — preset gpu→cpu 전환 시 mixed-model transcript pool 생성
  - 증거: 일부 영상은 `large-v3:int8_float16`, 나머지는 `medium:int8` 로 생성된 transcript 가 동일 pool 에 혼재. find_match_spans 의 segment boundary 가 모델마다 달라 비교 정확도 저하.
  - 수정 권고: OPEN-H 결정 시 "모델 버전 불일치 시 warn + 재처리 옵션" 포함.

- **SB-4.c** (재발 위험도: Medium) — 동일 채널 재ingest 시 partial update 후 nC2 pool 불일치
  - 증거: 일부 영상만 재처리(--force 부분 적용) 시 transcript 날짜가 섞여 비교 결과 해석 불명확.
  - 수정 권고: `--force` 실행 시 감사 CSV 에 `forced_reprocess` 이유와 이전 source 필드 기록 권장.

---

## 4. 미해결 사항 (Open)

1. **OPEN-A** (가장 시급) — [추가 OPEN, **cuRAND 제거 정정**] — ctranslate2 4.7.1 dlopen 대상 2개(`libcublas.so.12`, `libcuda.so.1`)를 `devShells.gpu` 에 link
   - 감사 근거: G-1.a (cuBLAS absent), G-1.b (shellHook LD_LIBRARY_PATH 누락). **G-4 binary analysis 정정**: cuRAND 는 dlopen 대상 아님. 추가 대상: `cudaPackages.libcublas` + `cudaPackages.cuda_cudart` buildInputs + shellHook 양쪽. ADV-15(ffmpeg timeout) 를 OPEN-A 후속 커밋에 포함 권장.
   - 다음 단계: PATCH 수준 코드 수정. 단독 커밋 권장 (bisect 추적성).

2. **OPEN-B** — [부분 확정] — 어제 22:00 시점 환경에서 cuBLAS 가 어디서 잡혔는지
   - 감사 근거: G-2.b (nixpkgs unstable float). 가설 G1 (시스템 cuBLAS `/usr/lib/cuda/...` 가 LD_LIBRARY_PATH 에 잔존하다가 셸 재진입 후 소실) 이 가장 유력하나, nix profile commit 스냅샷 없이 확정 불가. 재현 불가로 간주해도 G-1.a/b fix 로 근본 원인 해소 예상.
   - 다음 단계: G-1.a fix 적용 후 동일 환경 재실행으로 검증.

3. **OPEN-C** — [완료] — §3 항목 전체 점검 결과 본 §3 감사 결과 섹션에 기재. qa-cross 통합 후: G(6건) / E(5건, ADV-1 포함) / I(5건, I-1.b 포함) / D(4건) / R(10건) / C(3건) / SB(6건) = 총 39건 finding.

4. **OPEN-D** — [추가 OPEN, 결정 대기] — 본 인시던트로부터 derive 되는 spec 또는 docs 갱신
   - 감사 근거: C-1.a (CLAUDE.md Consistency Invariants 섹션 신설), D-1.a/D-2.a (quickstart.md GPU 섹션 신설), E-1.a (uv tool 설치 권장 명령), E-2.a (수동 검증 절차), R-4.a/R-7.a (실패 사유 출력), BUX-1 (진행률 표시 개선), R-12.a (help 텍스트). 코드 수정은 PATCH 수준, docs 갱신은 contribution-guide 갱신 필요.
   - 다음 단계: 사용자가 PATCH vs 신규 spec 결정.

5. **OPEN-E** — [결정 대기] — 본 세션 임시 fake row (`동영상(99).csv`) 정리 시점
   - 감사 근거: R-2.a — 데이터 오염 위험. 중복 검출 테스트 완료 시 즉시 삭제 권장.

6. **OPEN-F** — [결정 대기] — `.envrc` / `.gitignore` / `flake.nix` 변경분 commit 여부
   - 감사 근거: G-1.a/b fix (flake.nix), D-2.a fix (.envrc + .gitignore) 는 함께 commit 권장.

7. **OPEN-G** (신규, **확장됨**) — 에러 분류 3-way: asr.py outer except + unified_ingest audit reason collapse + CLI 실패 사유 출력
   - 감사 근거: E-3.a(정정) + **ADV-1(권위 finding 승격)** + R-7.a. 세 항목이 같은 "진단 지연" 문제의 다른 계층.
     - E-3.a: `asr.py:562-564` outer except 가 cuBLAS OSError 를 RuntimeError 로 래핑 — CUDA lib missing 키워드 감지 후 분류 메시지 출력으로 개선.
     - ADV-1: `unified_ingest.py:269/316/361` audit CSV reason collapse → `sub_reason`/`error_class` 컬럼 추가로 cuBLAS-missing / OOM / 패키지 미설치 구별.
     - R-7.a: CLI 종료 시 failure_reason 상위 3건 콘솔 출력 추가.
   - ADV-1 fix cascade: ADV-2/16/17/19 + E-4.a 5건 동시 해소.
   - 다음 단계: PATCH 수준. asr.py + unified_ingest.py 를 별도 커밋 또는 같은 커밋으로 처리 — 사용자 결정.

8. **OPEN-H** (신규, **확장됨**) — already_transcribed skip 모델 버전 검증 정책 결정
   - 감사 근거: I-1.a + I-1.b + ADV-20 + SB-4.a/b. 모두 `unified_ingest.py:148` 파일 존재만 체크가 root cause. I-1.b 는 `_check_already_processed` 시그니처 변경 필요로 설계 변경 동반.
   - 선택지: (a) warn-only (source 불일치 시 콘솔 경고) (b) force-reprocess (불일치 시 재처리) (c) 현행 유지 + `--force` 문서화. **F-1 적용 완료 직후 결정 권장** — F-1 이후에도 nixpkgs 업데이트 시 stale transcript 재사용 경로 잔존.
   - 다음 단계: 사용자 정책 결정 후 spec 018 PATCH 또는 신규 spec.

9. **OPEN-I** (신규) — SB-1: 2.4M pairs O(n²) — spec 019 진입 조건 확인
   - 감사 근거: SB-1 — 22채널 × 100영상 기준 2.4M pairs. Layer-A upfront cull 없어 GPU pool 없이 실용적 처리 불가.
   - 다음 단계: spec 019 진입 조건 2개(22부서 ingest 완료, 실제 cross-dept pair 확인) 충족 여부 사용자 결정.

10. **OPEN-J** (신규) — ADV-15: audio_extract.py ffmpeg subprocess timeout 부재
    - 감사 근거: ADV-15 — `audio_extract.py:51` 에 `timeout=` 없음. 손상 mp4 1건으로 전체 ingest hang 가능.
    - 다음 단계: P1 one-liner fix — `subprocess.run(cmd, ..., timeout=600)` 추가. OPEN-A 후속 커밋에 포함 권장.

---

## 5. 영향받은 파일 (참조용)

### 5.1 코드/설정 (assistant 가 손댐)
- `flake.nix:55-60` (sqlite 추가)
- `.envrc:8-10` (source_env_if_exists)
- `.gitignore:28-29` (.envrc.local)

### 5.2 데이터/CSV (assistant 가 손댐)
- `data/takeout-20260511T130817Z-3-001/Takeout/YouTube 및 YouTube Music/동영상 메타데이터/동영상(99).csv` (신규, 1 fake row)

### 5.3 코드 전수조사 1차 대상
- `src/tube_scout/services/asr.py` (lazy import 메시지 false attribution 가능성)
- `src/tube_scout/services/unified_ingest.py` (idempotency 정책)
- `src/tube_scout/services/transcript_*` (ASR 결과 metadata 검증)
- `pyproject.toml` (`[asr]` extra 의 ctranslate2 핀)
- `flake.nix` (`devShells.gpu` 의 cudaPackages)
- `docs/quickstart.md` / `docs/tutorial.md` (사용자 setup 가이드 — 본 인시던트 재발 방지 항목 포함 여부)

---

## 6. 다음 액션 (사용자 결정 대기)

- [x] 코드 전수조사 진행 — §3 의 G/E/I/D/R/C/SB 항목 감사 완료 (2026-05-17, audit_consistency_20260517_g_d_c.md + qa_cross.md + src/ spot-check)
- [x] 점검 결과를 본 문서 §3·§4 에 in-place 갱신 (2026-05-17, pair-programmer 통합 × 2회차. qa-cross 53건 추가)
- [x] remediation plan 작성 완료 (2026-05-17, `_workspace/audit_consistency_20260517_remediation_plan.md`)
- [ ] **[결정 대기]** OPEN-A fix: flake.nix cuBLAS + cudart 추가 (cuRAND 제거 정정) — P0 PATCH, 단독 커밋
- [ ] **[결정 대기]** OPEN-J fix: audio_extract.py ffmpeg timeout=600 추가 — P1 one-liner, OPEN-A 후속
- [ ] **[결정 대기]** OPEN-G fix: asr.py CUDA 에러 분류 + unified_ingest audit sub_reason 컬럼 — P1 PATCH
- [ ] **[결정 대기]** OPEN-D docs 갱신: quickstart.md GPU 섹션 + CLAUDE.md Consistency Invariants (contribution-guide 수준, spec 불필요)
- [ ] **[결정 대기]** OPEN-H 정책 결정: already_transcribed skip 모델 버전 검증 (warn-only / force-reprocess / 현행+--force 문서화)
- [ ] **[결정 대기]** OPEN-I spec 019 진입 조건 확인: 2.4M pairs 가속 여부
- [ ] **[결정 대기]** OPEN-E 임시 산출물 (`동영상(99).csv`, `42- 2 ... 7주차 ...mp4`) 정리 시점
- [ ] **[결정 대기]** OPEN-F `.envrc` / `.gitignore` / `flake.nix` 변경분 commit
