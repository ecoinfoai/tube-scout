# Phase 0 Research: Takeout 기반 로컬 ASR + 강의 영상 재사용 판정 + 자막 KB Export

**Spec**: [spec.md](./spec.md) · **Plan**: [plan.md](./plan.md)

본 문서는 plan.md의 Technical Context에서 도출된 unknown · best-practice 항목을 해소하고, 각 결정에 대해 (Decision / Rationale / Alternatives considered) 형식으로 동결한다. 모든 의사결정은 spec.md FR 또는 §Clarifications 답변에 매핑된다.

---

## R-1. 로컬 STT 백엔드 선정

**Unknown 원천**: FR-016 "local STT backend supporting GPU acceleration + int8 quantization + configurable model size/precision/device". idea 문서는 faster-whisper를 권장했으나 plan 단계에서 alternative 정량 비교 필요.

**Decision**: `faster-whisper>=1.0.0` (CTranslate2 backend) 채택.

**Rationale**:
- **속도**: OpenAI Whisper 본가(transformers + torch) 대비 동일 정확도 기준 4~5배 빠름(CTranslate2 inference). 6 GB VRAM RTX 3060 Laptop에서 `large-v3` + `int8_float16` 가 메모리 fit.
- **메모리**: `int8` 양자화로 large-v3 VRAM 사용량 ~1.5 GB(원본 ~3 GB의 절반 이하). spec 011/007이 사용하는 sentence-transformers + 동일 GPU에 공존 가능.
- **의존성 surface**: faster-whisper는 ctranslate2 + tokenizers + huggingface-hub만 의존(transformers / torch 미의존). pyproject.toml `dependencies`에 한 줄 추가, optional extra `asr` 분리 가능.
- **API 안정성**: `WhisperModel(model_size, device, compute_type)` + `model.transcribe(audio_path, ...)` 시그니처가 README에 명시되어 `# [VERIFY]` 해소 가능. 본 plan 시점에 GitHub README 확인 — `WhisperModel.transcribe()` 가 segments iterator를 반환하고 `vad_filter`, `condition_on_previous_text`, `compression_ratio_threshold`, `no_speech_threshold` 옵션 실재.
- **VAD 통합**: faster-whisper 1.0+는 silero-vad를 내장(onnxruntime 의존). `--vad-filter on`은 추가 모델 없이 활성화됨.
- **언어 강제**: `language="ko"` 인자로 한국어 강제, language_mismatch flag 검출에 사용.

**Alternatives considered**:
- **OpenAI Whisper (`openai-whisper` PyPI)**: 본가 구현, transformers + torch 직접 의존. 의존성 surface 크고 6 GB VRAM에 large-v3 fit 불가(원본 정밀도 시). int8 양자화 미지원. **기각**.
- **WhisperX**: faster-whisper 기반에 화자 분리 + word-level alignment 추가. 화자 분리는 본 spec scope OUT(FR-052), word-level은 분석에 불필요. 추가 의존성(pyannote-audio + torch) 부담. **기각**.
- **openai-whisper-onnx / whisper.cpp**: onnxruntime / 순수 C++ 백엔드. faster-whisper 대비 large-v3 정확도 손실 보고가 일관되지 않음. CTranslate2 만큼 검증 사례 없음. **기각**.
- **Cloud STT (OpenAI Whisper API / Google / Naver / Azure)**: FR-048 영구 금지. **명시 기각**.

---

## R-2. Whisper Hallucination 방어 4종 기본값 검증

**Unknown 원천**: FR-017 "VAD on / condition_on_previous_text off / compression_ratio_threshold 2.4 / no_speech_threshold 0.6 강제". 각 임계값이 강의 영상 도메인에 적합한지 docs/공개 사례 기반 검증 필요.

**Decision**: idea §7.4 값을 그대로 채택하되 PoC 영상 1편 + long-form 1편으로 SC-004 검증.

| 옵션 | 기본값 | Rationale |
|---|---|---|
| `vad_filter` | True | silero-vad 내장, 무음 구간 사전 제거. 강의 영상은 판서·학생 응답으로 무음 비중 큼. |
| `condition_on_previous_text` | False | 환각 텍스트의 self-reinforcing 연쇄 차단. faster-whisper README가 권장(특히 한국어). |
| `compression_ratio_threshold` | 2.4 | Whisper 본가의 권장 임계. 반복 텍스트는 gzip 압축률이 급등 — 임계 초과 세그먼트 drop. |
| `no_speech_threshold` | 0.6 | 무음 확률 임계. 0.6은 OpenAI Whisper README가 명시한 기본값과 일치. |

**Rationale**:
- 강의 도메인 특성상 무음·반복 구간이 많아 4종 모두 의미 있음. idea §7.4가 명시적 운영자 결정으로 임계값을 동결했고, plan 단계에서 임계 재산정 근거가 없음.
- SC-004 검증: PoC 영상(`5-1.임경민`, 105초) + 1개 long-form 영상(40분+) → `asr_quality_flags.hallucination_repeat` / `.silence_hallucination` 비율 측정 후 baseline 동결.

**Alternatives considered**:
- **compression_ratio_threshold 2.0 / 3.0**: 2.0은 정상 텍스트도 drop 위험, 3.0은 환각 통과 위험. 2.4가 균형점. **기각**.
- **no_speech_threshold 0.5**: 무음 오인 위험. 0.6이 보수적. **기각**.

---

## R-3. Evidence Score 가중치·임계 출발점

**Unknown 원천**: FR-003/FR-004 "+40 / +30 / +25 / +5 / +5 가중치, 65 / 40 임계". idea가 출발점으로 명시했으나 실측 검증 필요.

**Decision**: idea §7.1 표의 가중치 + 임계를 Phase 1 출발점으로 동결, 1차 Takeout 9개 영상으로 자동화율 측정 후 spec follow-up에서 commit.

**Rationale**:
- 5종 신호(파일명 정확 일치 / 정규화 일치 / duration / 크기 sanity / mtime)는 서로 독립적이고 각각 단독으로는 false positive 가능 — 가중치 합산이 자연스러움.
- mtime은 +5로 보조 신호로만 — 압축 해제·복사·외장 디스크 동기화로 손상 가능(idea Edge Case 명시).
- 임계 65/40은 "두 신호 일치(40+25)"에서 high 진입, "한 신호 일치(40)"에서 medium 진입을 의미. 1차 Takeout 9개 영상은 모두 high 진입 예상(파일명 정확 일치 + duration ±1초).

**Measurement plan** (Phase 1):
1. 1차 Takeout 9 mp4에 대해 Evidence Score 계산 → score 분포 측정.
2. 자동화율(high + medium 비율) = N(high) + N(medium) / 9.
3. ambiguous(score < 40) 케이스 0건이면 임계 65/40 유지, 1건 이상이면 신호 breakdown 점검 후 가중치 조정.
4. 측정 결과는 `_workspace/measurement/evidence_score_phase1.md` 에 기록 후 spec.md FR-004에 commit.

**Alternatives considered**:
- **단일 결정 신호(예: filename 정확 일치만)**: edge case(255자 절단, 특수문자 차이) 처리 불가. **기각** — idea §7.1 명시.
- **외부 fuzzy matching 라이브러리(rapidfuzz)**: 정규화 + Levenshtein 거리 도입. 의존성 추가. 본 spec은 `python-Levenshtein` 이미 보유 — 필요 시 활용 가능(score 신호 추가는 follow-up).

---

## R-4. fingerprint_input_policy 기본값 측정

**Unknown 원천**: FR-014 "fingerprint_input_policy default 미확정 — Phase 1 측정 후 commit".

**Decision**: 기본값 미확정 유지. Phase 1에 측정 task 분리.

**Measurement plan**:
1. 1차 Takeout 9개 영상에 대해 3 정책(`original_mp4`, `wav_16k`, `wav_22k`)으로 각각 chromaprint 지문 산출.
2. 동일 영상 정책 간 hamming distance 측정 (`services/audio_fingerprint.py:144 hamming_distance_per_int`).
3. 결과 분석:
   - 세 정책 결과 hamming distance가 noise 수준(예: < 5%)이면 `wav_16k` 채택 — STT 입력과 통합으로 디코딩 비용 절약.
   - 차이가 크면 `original_mp4` 또는 `wav_22k` 채택 — STT 입력과 분리, 디코딩 두 번 발생.
4. 결과는 `_workspace/measurement/fingerprint_policy_phase1.md` 기록 후 spec.md FR-014에 commit.

**Rationale**: 측정 없이 기본값을 결정하면 (a) 동일 영상이 정책에 따라 지문이 달라져 spec 011 시계열 비교 단절, 또는 (b) 디코딩 비용 낭비. 측정 후 합리화가 필수.

**Alternatives considered**:
- **`wav_22k` 무조건 채택 (chromaprint canonical)**: 디코딩 두 번. 측정 결과가 정책 일치를 보이면 비효율. **기각**.

---

## R-5. 단일 의심 점수(aggregate suspicion score) 형식

**Unknown 원천**: C-3 (clarification) "Multi-axis 한시 + 30일 후 가중치 합산 commit". Phase 3 출시 시점 보고서 구조 동결 필요.

**Decision**: Phase 3 보고서는 multi-axis 정렬(`--sort-by <metric>`), per-metric 임계 컷(`--appendix-threshold-<metric>`), per-metric 분포 히스토그램. Single aggregate score 컬럼 미생성. 30일 누적 후 spec follow-up에서 다음 commit:
- 가중치 합산 공식 (예: `score = 0.30·i2 + 0.25·i6 + 0.15·i7 + 0.15·i8 + 0.15·audio_fp_norm`)
- `comparison_results.aggregate_suspicion_score` 컬럼 ALTER ADD
- `--appendix-threshold <0..1>` 단일 옵션 도입
- 기존 per-metric 옵션 deprecated 표시(2 release 후 제거)

**Rationale**:
- C-3 옵션 D 채택 — appendix-threshold 정책(FR-038)이 이미 30일 한시 운영을 명시했으므로 점수 정의도 정렬.
- 30일 데이터로 axis별 변별력 확인 후 가중치 결정이 데이터 기반 의사결정에 부합.
- Phase 3 출시 시점에 임의 가중치를 commit하면 30일 후 변경 시 보고서 비교성 손상.

**Measurement plan (30일 후)**:
1. 30일 누적 운영자 검토 결과(`review_status='CONFIRMED_DUPLICATE'` vs `'FALSE_POSITIVE'`)와 각 axis 점수 분포 비교.
2. ROC curve / Logistic regression으로 axis별 가중치 도출.
3. 결과는 별도 idea 또는 spec amendment로 commit.

**Alternatives considered**:
- **즉시 가중치 동결(C-3 옵션 A)**: 실데이터 미확보 상태에서 가중치 부여는 추측. **기각**.
- **Max-of-normalized(C-3 옵션 B)**: 단일 noise signal이 grade 과대 평가. **기각**.

---

## R-6. audit_writer 8-stage 일반화 + Phase 4 잔존 정책

**Unknown 원천**: C-2 "spec 012 audit_writer 인프라 계승·확장 + Phase 4 yt-dlp 삭제 시 audit_writer는 분리 유지". 잔존 위치와 인터페이스 확정 필요.

**Decision**:
- `services/audit_writer.py`는 위치 변경 0 (그대로 유지).
- 클래스 인터페이스는 8 stage 일반화: `AuditWriter(project_dir).append_row(stage, row_dict)` + 단계별 frozen fieldnames는 모듈 상수로 정의.
- 기존 `append_transcript_row`, `append_fingerprint_row` 메서드는 Phase 1~3 동안 backward-compat shim으로 유지 → Phase 4에서 일반화 인터페이스만 남기고 제거.
- 단계별 fieldnames 동결 schema:

```python
TAKEOUT_INGEST_FIELDNAMES = ("video_id", "result", "reason", "mp4_filename", "match_confidence", "score", "timestamp")
AUDIO_EXTRACT_FIELDNAMES = ("video_id", "result", "reason", "input_kind", "output_path", "wav_size_bytes", "elapsed_s", "timestamp")
TRANSCRIPTS_FIELDNAMES = ("video_id", "result", "reason", "source", "caption_source_detail", "timestamp", "cookies_source")  # spec 012 호환 + caption_source_detail 추가
FINGERPRINT_FIELDNAMES = ("video_id", "result", "reason", "duration_sec", "fingerprint_input_policy", "timestamp", "cookies_source")  # 동상 + fingerprint_input_policy 추가
NORMALIZE_FIELDNAMES = ("video_id", "result", "reason", "input_source", "normalizer_version", "timestamp")
ANALYZE_FIELDNAMES = ("pair_id", "source_video_id", "target_video_id", "result", "reason", "matching_mode", "elapsed_s", "timestamp")
REPORT_FIELDNAMES = ("professor", "channel", "result", "reason", "format", "output_path", "pair_count", "appendix_count", "timestamp")
KB_EXPORT_FIELDNAMES = ("video_id", "result", "reason", "format", "output_path", "byte_count", "timestamp")
```

**Rationale**:
- spec 012가 이미 `audit_writer.py`를 service-layer에 위치시켰고, 단계별 frozen fieldnames + append-only + atomic tempfile rename 패턴 검증 완료(spec 012 master).
- 일반화 인터페이스는 메서드 추가 + 기존 메서드 보존으로 backward-compat 0 손상.
- Phase 4 yt-dlp 삭제 시 `audit_writer.py`는 ytdlp 흐름과 분리되어 있으므로(이미 cross-stage 사용 의도) 코드 위치 변경 불필요. spec.md FR-060이 이를 강제.

**Alternatives considered**:
- **`services/_common/audit_writer.py`로 이동**: 명시적 cross-stage 표시. 그러나 import 경로 변경이 spec 012 master 회귀 테스트 영향. 위치 그대로 유지가 더 단순. **기각**.
- **SQLite audit_events 테이블 단독(C-2 옵션 C)**: clarification에서 명시 기각. **기각**.

---

## R-7. Progress reporter — TTY 자동 감지

**Unknown 원천**: C-4 "sys.stdout.isatty() 분기 강제". helper 모듈 시그니처 동결 필요.

**Decision**: `services/progress_reporter.py` 신규 — context manager 인터페이스 + rich.progress / structured log line 자동 분기.

```python
def make_progress_reporter(stage: str, total: int) -> ProgressReporter:
    """Return a stage-aware progress reporter that auto-adapts to TTY/non-TTY."""

class ProgressReporter:
    def __enter__(self) -> "ProgressReporter": ...
    def update(self, video_id: str, n: int) -> None: ...  # n = current index (1-based)
    def __exit__(self, *exc_info) -> None: ...
```

내부 구현:
- TTY: `rich.progress.Progress(SpinnerColumn(), BarColumn(), TextColumn("[bold blue]{task.fields[video_id]}"), TimeElapsedColumn(), TimeRemainingColumn())` 한 개 task.
- 비-TTY: 매 update마다 한 줄 print — `f"[{stage}] video_id={video_id} N={n}/total={total} elapsed={elapsed}s ETA={eta}s"` 형식. 매 N영상 또는 매 K초마다(둘 중 짧은 쪽) 출력 — 19,900쌍 분석 시 매쌍 출력 과다.

ETA 계산: 단순 산술 — `eta = (total - n) * (elapsed / n)`. 안정성을 위해 첫 3쌍/영상 동안은 ETA 미표시.

**Rationale**:
- rich가 이미 dependency. 추가 의존성 0.
- isatty() 분기는 표준 Python 패턴, 외부 라이브러리 없이 안정.
- structured log line 형식은 grep/awk 친화 — 운영자 사후 분석 용이.

**Alternatives considered**:
- **tqdm**: rich 보다 가볍지만 비-TTY 분기 표현이 빈약. rich를 이미 보유 — **기각**.
- **per-pair JSON Lines log**: 19,900쌍 × 한 줄 = 19,900줄. cron log 부담. N영상/K초 throttle이 합리. **기각**.

---

## R-8. Worker pool — prod-a6000-pool 구현 방식

**Unknown 원천**: FR-022 "두 Python worker processes, cuda:0/cuda:1 pinned, SQLite atomic claim". 다중 프로세스 동기화 방식 + retry-failed 통합(C-5) 검증.

**Decision**:
- 두 개의 별도 Python 프로세스를 `Popen` 또는 `multiprocessing.Process`로 spawn — 각 프로세스가 `CUDA_VISIBLE_DEVICES=0` / `=1` 환경 격리.
- 공유 큐는 SQLite `processing_status` 테이블. WAL 모드 강제(`PRAGMA journal_mode=WAL;`) — 기본 rollback 모드는 reader/writer concurrency 미지원, WAL은 reader 무한 + writer 1개 동시 가능.
- Atomic claim 트랜잭션:

```sql
BEGIN IMMEDIATE;
SELECT video_id FROM processing_status
 WHERE status IN ('collected', 'asr_failed')
   AND caption_source IS NULL
 ORDER BY updated_at ASC
 LIMIT 1;
-- claim
UPDATE processing_status
   SET status = 'asr_in_progress',
       updated_at = CURRENT_TIMESTAMP
 WHERE video_id = ?
   AND status IN ('collected', 'asr_failed')
   AND caption_source IS NULL;
COMMIT;
```

`BEGIN IMMEDIATE` 가 reserved lock을 즉시 획득하여 두 워커 race 방지. UPDATE의 WHERE 조건이 status를 재확인하여 멱등성 보장 — 다른 워커가 같은 row를 먼저 claim했으면 affected rows = 0, 워커는 다음 row로 진행.

**Rationale**:
- `CUDA_VISIBLE_DEVICES` 환경 분리는 faster-whisper docs가 명시한 multi-GPU 패턴. 한 프로세스가 양쪽 GPU를 보지 않으므로 device_index 옵션 단순.
- SQLite WAL 모드는 spec 007/011/012가 이미 사용(content_db.py 검증 완료). 별도 큐 인프라(Celery/Redis) 도입 불필요(Constitution V).
- `BEGIN IMMEDIATE`는 SQLite docs가 multi-writer 패턴으로 권장 — DEFERRED 트랜잭션은 SQLITE_BUSY 폭증 위험.
- `RETURNING` 절(SQLite 3.35+)을 사용하면 SELECT + UPDATE 2단계를 1단계로 축약 가능 — NixOS devShell SQLite 3.45 보유 확인 필요(B-12).

**Alternatives considered**:
- **multiprocessing.Queue (in-memory)**: 프로세스 재시작 시 작업 큐 손실. SQLite 영속 패턴이 우위. **기각**.
- **Celery + Redis**: 외부 DB 도입 — Constitution V 위반. **명시 기각**.
- **`torch.multiprocessing` + DataParallel**: faster-whisper는 ctranslate2 기반이라 torch DataParallel 미적용. **기각**.

---

## R-9. M-nC2 매칭 모드 + 4계층 오탐 방어 완성

**Unknown 원천**: B-4 boundary — spec 011 P1 미완 부분의 미구현 함수 정확한 surface 확인.

**Decision**: spec 011 spec.md / data-model.md / contracts/ 산출물을 권위 참조 문서로 그대로 채택. 본 spec에서 추가 자율 결정 없음. 구현은 다음 함수 시그니처를 완성한다(이미 spec 011 contracts/에 동결되어 있음):

- `services/nc2_matcher.py::generate_nc2_pairs(professor: str, db: ContentDB) -> Iterator[VideoPair]`
- `services/time_axis_indicators.py::compute_i6_longest_contiguous(spans: list[MatchSpan]) -> float`
- `services/time_axis_indicators.py::compute_i7_distribution_dispersion(spans: list[MatchSpan]) -> float`
- `services/time_axis_indicators.py::compute_i8_position_diversity(spans: list[MatchSpan], src_duration: float, tgt_duration: float) -> float`
- `services/layer_defense.py::apply_layer_a(spans, min_seconds: float) -> list[MatchSpan]`
- `services/layer_defense.py::apply_layer_b(spans, prof_baseline: BaselineCorpus) -> list[MatchSpan]`
- `services/layer_defense.py::apply_layer_c(spans, dept_idf: IDFCorpus) -> list[MatchSpan]`
- `services/layer_defense.py::apply_layer_d(pair_id: str, db: ContentDB) -> ReviewStatus | None`
- `services/pattern_classifier.py::classify(pair: ComparisonResult, src_duration: float, tgt_duration: float, audio_fp_hamming: int | None) -> ReusePatternLabel`

**신설 2 패턴 정의**:
- `re-recorded-same-content`: `i2_cosine ≥ 0.85` AND `audio_fp_hamming > <threshold>` (음원은 다름). Phase 3 측정 후 audio_fp_hamming 임계 동결.
- `tail-update`: `i8_position_diversity` 의 영상 시간축 전반부(0~50%) ≥ 0.85 AND 후반부(50~100%) ≤ 0.15. half-split 함수가 `match_spans` 시계열을 두 구간으로 나눠 측정.

**Rationale**: spec 011은 본 spec의 prior, B-4 boundary가 spec 011의 시그니처 + 컬럼명을 권위로 묶음. 본 spec이 시그니처를 변경하면 spec 011 의도와 충돌 — 변경 0건 원칙.

---

## R-10. Text Normalizer 규칙 동결

**Unknown 원천**: FR-024 "punctuation removal, whitespace collapse, NFC, lowercase, ASR meta-marker stripping". 정확한 정규식과 적용 순서 동결 필요.

**Decision**: 정규화 파이프라인 순서 (멱등):

```python
def normalize_transcript_text(text: str) -> str:
    # 1) NFC unicode normalization (한글 자모 단독 표기 → 결합형)
    text = unicodedata.normalize("NFC", text)
    # 2) ASR meta-marker strip — [음악], [박수], (...), <...>, *...*, ♪...♪
    text = re.sub(r"\[[^\]]*\]|\([^\)]*\)|<[^>]*>|\*[^\*]*\*|♪[^♪]*♪", " ", text)
    # 3) Punctuation removal (한글 + ASCII)
    text = re.sub(r"[.,?!~…\"'`‘’“”、。]", " ", text)
    # 4) Whitespace collapse (모든 공백류 → 단일 공백, 줄바꿈 제거)
    text = re.sub(r"\s+", " ", text)
    # 5) Lowercase folding for Latin chars only (한글은 영향 없음)
    text = text.lower()
    return text.strip()
```

정규화 버전 식별자: `normalizer_version='v1.0'`. 향후 규칙 변경 시 `v1.1` 등으로 bump, 정규화 결과 파일에 메타로 저장.

**Rationale**:
- NFC 우선 — meta-marker 안에 자모 단독이 있어도 후속 정규식이 안정.
- meta-marker 제거 시 공백으로 교체 — 인접 단어 결합 방지.
- 구두점 → 공백 동상.
- whitespace collapse는 마지막 직전 — 모든 변환의 공백 누적 흡수.

**Alternatives considered**:
- **lowercase 전체(한글 포함)**: 한글은 `str.lower()` 변화 없음 — 동일 결과. 그러나 명시적 의도 표현 위해 Latin chars only 주석.
- **순수 stopword 제거 추가**: 한국어 stopword 목록 불일치 우려, false negative 위험. 본 normalizer scope OUT. **기각**.

---

## R-11. v4 마이그레이션 패턴

**Unknown 원천**: FR-043/044/045 "신규 테이블 2개 + 기존 4 테이블 ALTER + 멱등 실행". SQLite ALTER 제약 검증 필요.

**Decision**: `storage/content_db.py::migrate_to_v4(db_path)` 함수 신규 — `_schema_version` 테이블의 user_version을 3 → 4로 bump. 멱등.

ALTER 패턴 (SQLite 3.35+):
- `processing_status`: `ALTER TABLE processing_status ADD COLUMN match_confidence TEXT;` + `ADD COLUMN caption_source_detail TEXT;` (NULL 허용 — 기존 row 자연 보존)
- `quality_results`: `ADD COLUMN asr_quality_flags TEXT;` (NULL = ASR 미실행, JSON 텍스트 = 측정 결과)
- `comparison_results`: `ADD COLUMN audio_fp_hamming INTEGER;` + `ADD COLUMN audio_fp_best_offset REAL;` + `ADD COLUMN audio_fp_overlap_seconds REAL;` + `ADD COLUMN source_type_pair TEXT;`

**CHECK constraint 미도입**: spec.md FR-023이 명시 — 기존 테이블에 CHECK 추가는 테이블 rebuild 필요(SQLite ALTER 제약). Python frozenset(`VALID_PROCESSING_STATUSES`)만 갱신, DB level CHECK는 follow-up migration으로 분리.

**신규 테이블**:
```sql
CREATE TABLE IF NOT EXISTS channel_metadata (
    channel_id           TEXT PRIMARY KEY,
    channel_alias        TEXT NOT NULL,
    title                TEXT,
    country              TEXT,
    privacy_status       TEXT,
    source               TEXT NOT NULL,
    takeout_root_hint    TEXT,
    ingested_at          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS video_metadata (
    video_id             TEXT PRIMARY KEY,
    channel_id           TEXT NOT NULL,
    title                TEXT NOT NULL,
    duration_seconds     REAL,
    language             TEXT,
    category             TEXT,
    privacy_status       TEXT,
    created_at           TEXT,
    published_at         TEXT,
    source               TEXT NOT NULL,
    match_confidence     TEXT,
    mp4_relative_path    TEXT,
    ingested_at          TEXT NOT NULL,
    FOREIGN KEY (channel_id) REFERENCES channel_metadata(channel_id)
);

CREATE INDEX IF NOT EXISTS idx_video_meta_channel ON video_metadata(channel_id);
CREATE INDEX IF NOT EXISTS idx_video_meta_privacy ON video_metadata(privacy_status);
```

신설 패턴 enum 확장: `comparison_results.reuse_pattern` 컬럼은 spec 011 코드에서 TEXT (CHECK constraint 없음) — 신설 2값 추가는 Python 측 `ReusePatternLabel` enum 갱신만으로 충분.

**Rationale**:
- ALTER ADD COLUMN은 SQLite가 빠르게 처리(메타데이터만 갱신, 기존 row 재작성 없음). 멱등성은 `_schema_version` 테이블 체크로 보장.
- 신규 테이블 `IF NOT EXISTS`는 spec 007 패턴 그대로.
- Foreign key는 SQLite default OFF — 본 spec은 `PRAGMA foreign_keys=ON` 강제 시점 코드 진입 시 enable.

**Alternatives considered**:
- **테이블 rebuild로 CHECK 일괄 추가**: 운영자 DB 크기에 따라 시간 비용. follow-up migration으로 분리가 합리. **기각(이번 spec에서)**.

---

## R-12. faster-whisper 모델 다운로드·캐시 전략

**Unknown 원천**: B-13 boundary — huggingface-hub 모델 캐시 위치 / 다운로드 시점 / 오프라인 운영.

**Decision**:
- 모델 캐시: `$HF_HOME` (운영자 환경변수) 또는 기본 `~/.cache/huggingface/hub/`. 본 spec은 캐시 위치를 강제하지 않음(운영자 환경 산출물 — Constitution V scope 외부).
- 다운로드 시점: 최초 `tube-scout collect transcripts --source asr` 실행 시 자동. 운영자 사전 다운로드는 quickstart.md에 안내 — `huggingface-cli download Systran/faster-whisper-large-v3` 명령.
- 오프라인 운영: 사전 다운로드된 캐시가 있으면 인터넷 없이 작동(faster-whisper offline mode). quickstart.md에 명시.
- 모델 식별: `caption_source_detail = "asr:faster-whisper:<model_size>:<compute_type>"` 형식. 모델 size 변경 시 detail 컬럼이 자동 분기 — 동일 video_id를 다른 모델로 재처리해도 출처 추적 가능.

**Rationale**:
- huggingface-hub는 익명 다운로드, agenix 무관(Constitution VI 일관).
- 캐시 위치 강제 미설정 — 운영자 환경 자유. 일관성 필요 시 `flake.nix devShell shellHook`에서 `export HF_HOME=…` 추가 가능.
- 오프라인 운영은 운영 GPU 서버(인터넷 격리 가능)에서 중요.

**Alternatives considered**:
- **모델 캐시를 repo 내부에 두기**: 모델 ~1.5 GB → git 부담. **기각**.
- **agenix로 모델 캐시 위치 secret 관리**: 모델은 secret 아님. **기각**.

---

## R-13. KB export 형식 디테일

**Unknown 원천**: FR-040 "txt / md / jsonl, BOM 없음, 타임스탬프 옵션". 형식별 정확한 schema 동결.

**Decision**:

- **`txt`**: 세그먼트 텍스트만 줄바꿈 구분, 빈 줄 없음. 헤더 없음. 파일명 `<video_id>.txt`.
  - 예: `안녕하세요 정광석 교수입니다\n오늘은 간호연구방법론 8주차 1차시입니다\n...`
  - `--keep-timestamps` 시 `[hh:mm:ss] 세그먼트 텍스트` 형식.

- **`md`**: 영상 메타 헤더 + 세그먼트 본문. 파일명 `<video_id>.md`.
  - 헤더: `# <title>\n\n- video_id: <id>\n- duration: <s>s\n- source: <ASR or API caption>\n\n---\n\n`
  - 본문: 세그먼트 텍스트 줄바꿈 구분.

- **`jsonl`**: 세그먼트당 한 줄 JSON. 파일명 `<video_id>.jsonl`.
  - 한 줄: `{"start": 0.0, "end": 3.5, "text": "안녕하세요 ..."}`
  - 영상 메타는 첫 줄 또는 별도 `<video_id>.meta.json` (`--with-meta` 플래그).

- **`--clean-fillers`**: 정규식으로 ASR 채움 표현(`음~`, `어~`, `에이`) 제거. 한국어 도메인 특화, 옵션이며 기본 off — 운영자가 외부 KB 도구에서 자체 정제할 수 있도록.

**Rationale**:
- 외부 KB 도구는 txt(검색 인덱스) / md(GitBook/RAG ingestor) / jsonl(LLM fine-tuning) 셋이 가장 일반적.
- UTF-8 BOM 없음 강제 — 외부 도구의 BOM 처리 비일관 회피.
- `--keep-timestamps` 기본 off — KB 입력은 통상 텍스트 흐름만 필요.

**Alternatives considered**:
- **SRT / VTT 출력**: 자막 표시용 형식, KB 입력에는 부적합. **기각**.
- **HTML 출력**: KB 입력은 평문 선호. **기각**.

---

## R-14. PoC 영상 검증 시나리오

**Decision**: PoC 영상 = `5-1.임경민_간호연구세미나_8주차_1차시` (video_id `sUJbkkYzNGc`, 105초). 1차 Takeout 9개 중 가장 짧음.

검증 항목:
1. mp4 → 16 kHz mono WAV 추출 성공 + WAV 파일 크기 ~3.4 MB(105초 × 16000 × 2 byte).
2. 기존 mp4 직접 입력 chromaprint 지문(spec 012 측정값) vs WAV 입력 chromaprint 지문 hamming distance.
3. faster-whisper `large-v3` + `int8_float16` + `cuda:0` 추론 → segments 추출 시간 ≤ 60초 (PoC GPU).
4. ASR 자막 quality flags 측정 — 105초는 강의 도입부, 환각 위험 낮음. baseline.
5. KB export txt 형식 산출.

---

## R-15. 1차 Takeout fixture 안전화

**Unknown 원천**: tests/fixtures에 1차 Takeout 데이터(9 mp4 + 39 CSV)를 어떻게 포함시킬지. mp4 9.9 GB는 git LFS 외 commit 불가.

**Decision**:
- 실 mp4 9개는 fixture에 포함하지 않음 — 운영자 로컬 머신에만 존재.
- 39 CSV의 sanitized 사본만 fixture에 포함 — 익명화(채널 ID, video_id, 제목)된 mini CSV(예: 9 video × 3 분할 = 27 row, 또는 9 video 압축 1 분할).
- mp4 ↔ video_id 매핑 검증은 fake mp4 (1 KB 더미 파일에 ffprobe-가능한 최소 헤더 포함) + sanitized CSV로 통합 테스트.
- `5-1.임경민` 실 영상은 `@pytest.mark.slow` + 환경변수 `TUBE_SCOUT_POC_VIDEO_PATH` 지정 시만 실행하는 manual test에 배치.

**Rationale**:
- mp4 9.9 GB git commit 불가 — repo 크기 부담.
- 익명화된 sanitized CSV는 spec 003/007 패턴(`tests/fixtures/`에 익명 video_id 사용) 일관.
- 실 데이터 의존 테스트는 `@pytest.mark.slow + manual fixture` 패턴 — spec 012가 이미 사용.

**Alternatives considered**:
- **git LFS로 mp4 commit**: 운영자 머신 외에는 활용 0, 비용 부담. **기각**.
- **다운로드 가능한 sanitized 영상 fixture (5초 합성 음성)**: faster-whisper 정확도 검증에 부적합(한국어 강의 자연 음성 필요). 단위 테스트는 fake fixture로 충분, 정확도 검증은 운영자 실 영상으로. **기각**.

---

## R-16. faster-whisper API 시그니처 [VERIFY] 해소

**Verified at plan time** (2026-05-13, faster-whisper GitHub README + PyPI 페이지 확인):

```python
from faster_whisper import WhisperModel

model = WhisperModel(
    model_size_or_path="large-v3",
    device="cuda",
    device_index=0,
    compute_type="int8_float16",
    download_root=None,  # default HF_HOME or ~/.cache/huggingface/
)

segments, info = model.transcribe(
    audio="path/to/audio.wav",
    language="ko",
    beam_size=5,
    vad_filter=True,
    condition_on_previous_text=False,
    compression_ratio_threshold=2.4,
    no_speech_threshold=0.6,
)

# segments is an iterator (lazy decode)
for segment in segments:
    print(segment.start, segment.end, segment.text)
```

옵션 모두 README 명시 — `# [VERIFY]` 해소. 단 PyPI 버전과 GitHub HEAD가 다를 수 있으므로 plan tasks에서 `>=1.0.0,<2.0.0` 핀 + 운영자 머신에서 `from faster_whisper import WhisperModel` import 성공 확인을 Phase 2 초입에 1회 수행.

---

## 미해결 항목 (Phase 1·2 측정 필요)

| 항목 | spec.md 참조 | 측정 시점 | 산출 위치 |
|---|---|---|---|
| Evidence Score 가중치/임계 튜닝 | FR-003/004, SC-003 | Phase 1 (9-video 측정) | `_workspace/measurement/evidence_score_phase1.md` |
| `fingerprint_input_policy` 기본값 | FR-014 | Phase 1 (3-policy hamming 비교) | `_workspace/measurement/fingerprint_policy_phase1.md` |
| Hallucination 잔여율 baseline | SC-004 | Phase 2 (PoC 영상 + long-form 1편) | `_workspace/measurement/hallucination_baseline_phase2.md` |
| ASR throughput PoC GPU | SC-002 | Phase 2 | `_workspace/measurement/asr_throughput_phase2.md` |
| ASR throughput prod GPU pool | SC-002, SC-010 | Phase 2 (GPU 서버 인계 시) | `_workspace/measurement/asr_throughput_prod_phase2.md` |
| nC2 분석 wall-clock 200영상 | SC-002 | Phase 3 | `_workspace/measurement/nc2_runtime_phase3.md` |
| Audio fp hamming 임계 (re-recorded 패턴) | FR-031, R-9 | Phase 3 | `_workspace/measurement/audio_fp_threshold_phase3.md` |
| Aggregate score 가중치 공식 | FR-036/038, C-3, R-5 | Phase 3 후 30일 | spec follow-up amendment |

각 측정은 별도 task로 `tasks.md`에 분리되며, 결과는 spec.md FR · SC 또는 spec follow-up amendment에 commit한다.

---

## Phase 0 결론

모든 [VERIFY] 항목 해소, NEEDS CLARIFICATION 0건. Phase 1 (data-model.md + contracts/ + quickstart.md) 진행 가능.
