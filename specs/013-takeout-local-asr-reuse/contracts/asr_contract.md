# Contract: services/asr.py

**Module**: `src/tube_scout/services/asr.py` (신규)
**Spec FR mapping**: FR-016~FR-023.
**Boundary**: B-13 (huggingface 모델 캐시), B-2 (processing_status / quality_results / caption_source_detail).

---

## 함수 시그니처

```python
from pathlib import Path
from typing import Literal
from tube_scout.models.content import AsrQualityFlags

ModelSize = Literal["tiny", "base", "small", "medium", "large-v3"]
ComputeType = Literal["float32", "float16", "int8_float16", "int8"]
Device = Literal["cuda", "cpu"]

PRESET_TABLE: dict[str, dict[str, str | int]] = {
    "poc-laptop":         {"model": "large-v3", "compute_type": "int8_float16", "device": "cuda", "device_index": 0},
    "prod-a6000":         {"model": "large-v3", "compute_type": "float16",       "device": "cuda", "device_index": 0},
    "prod-a6000-pool":    {"model": "large-v3", "compute_type": "float16",       "device": "cuda", "device_index": None},  # worker pool sets per-process
    "cpu-fallback":       {"model": "medium",   "compute_type": "int8",          "device": "cpu",  "device_index": 0},
}

class TranscribeResult(BaseModel):
    segments: list[Segment]       # {start: float, end: float, text: str}
    language_detected: str
    duration: float
    asr_quality_flags: AsrQualityFlags
    caption_source_detail: str    # 'asr:faster-whisper:<size>:<compute_type>'


def transcribe_audio(
    wav_path: Path,
    *,
    model_size: ModelSize = "large-v3",
    compute_type: ComputeType = "int8_float16",
    device: Device = "cuda",
    device_index: int = 0,
    language: str = "ko",
    beam_size: int = 5,
    vad_filter: bool = True,
    condition_on_previous_text: bool = False,
    compression_ratio_threshold: float = 2.4,
    no_speech_threshold: float = 0.6,
    model_cache_dir: Path | None = None,
) -> TranscribeResult:
    """Transcribe a 16 kHz mono WAV via faster-whisper.

    Hallucination defenses (FR-017) are enforced as defaults; opt-out via
    explicit args.

    Args:
        wav_path: 16 kHz mono PCM WAV.
        model_size: large-v3 권장 (한국어).
        compute_type: int8_float16 (6 GB VRAM), float16 (24+ GB VRAM).
        device: cuda 또는 cpu.
        device_index: GPU 인덱스 (multi-GPU pool 시 워커별 설정).
        language: 'ko' 강제 (자동 감지 비활성).
        beam_size: 5 (기본). 1=greedy.
        vad_filter: True (FR-017 default).
        condition_on_previous_text: False (FR-017 default).
        compression_ratio_threshold: 2.4 (FR-017 default).
        no_speech_threshold: 0.6 (FR-017 default).
        model_cache_dir: None=HF_HOME 기본. 명시 시 download_root 인자로 전달.

    Returns:
        TranscribeResult with segments + language + quality flags + caption_source_detail.

    Raises:
        ImportError: faster-whisper 미설치 (actionable message — 'pip install tube-scout[asr]').
        FileNotFoundError: wav_path 부재.
        RuntimeError: faster-whisper internal error (CUDA OOM, model load 실패 등 — message에 원인 포함).
    """
```

---

## Hallucination 방어 implementation

`transcribe_audio` 내부:

1. **VAD**: `vad_filter=True` 인자를 faster-whisper에 그대로 전달. silero-vad가 내장 동작.
2. **No previous-text conditioning**: `condition_on_previous_text=False` 인자 전달.
3. **Compression ratio**: faster-whisper가 임계 초과 세그먼트를 자동 drop. drop된 횟수는 segments_info iterator의 logprob/compression_ratio에서 측정 후 `asr_quality_flags.compression_ratio_violations` 카운트.
4. **No-speech threshold**: 세그먼트별 `no_speech_prob` 검사 — 0.6 초과면 segments에서 제외.

**후처리 quality flag 검출**:

```python
def detect_quality_flags(segments: list[Segment], language_detected: str, expected_lang: str) -> AsrQualityFlags:
    """Detect 6 ASR quality issues post-transcription."""
    return AsrQualityFlags(
        hallucination_repeat = _detect_repeat_n(segments, n=3),
        vad_over_truncated   = _detect_vad_over_truncation(segments, audio_duration),
        language_mismatch    = language_detected != expected_lang,
        short_segments_excess= _ratio_short_segments(segments, threshold=0.5, ratio=0.30),
        silence_hallucination= _detect_silence_filler(segments),
        compression_ratio_violations = _count_compression_violations(segments),
    )
```

`_detect_repeat_n(segments, n=3)`: 연속 3개 세그먼트의 text가 정규화 후 동일하면 True.

`_detect_silence_filler`: "구독과 좋아요", "시청해주셔서 감사합니다", "구독 부탁드립니다" 등 학습 잔재 패턴 정규식 검출 — 강의 도메인에 등장 가능성 0, 등장 시 hallucination 강한 신호.

---

## Caption source detail 포맷 (FR-020)

```
asr:faster-whisper:<model_size>:<compute_type>
```

예:
- `asr:faster-whisper:large-v3:int8_float16` (PoC GPU)
- `asr:faster-whisper:large-v3:float16` (prod A6000)
- `asr:faster-whisper:medium:int8` (CPU fallback)

API caption 출처는 `api:captions_api:youtube-data-v3` (기존 spec 010 호환 위해 별도 정의).

---

## 모델 로드 캐시

`WhisperModel` 인스턴스는 프로세스 내 module-level singleton(또는 lru_cache)로 캐시 — 한 워커가 N개 영상 처리 시 모델 1회 로드. 워커 풀에서는 각 프로세스가 자체 인스턴스 보유(CUDA context 분리).

```python
@functools.lru_cache(maxsize=1)
def _load_model(model_size: ModelSize, compute_type: ComputeType, device: Device, device_index: int, model_cache_dir: Path | None) -> "WhisperModel":
    from faster_whisper import WhisperModel
    return WhisperModel(model_size, device=device, device_index=device_index, compute_type=compute_type, download_root=str(model_cache_dir) if model_cache_dir else None)
```

`lru_cache` 키가 동일하면 같은 인스턴스 반환 — 운영자 옵션 변경 시 새 인스턴스 로드.

---

## ImportError 처리 (Constitution II)

`from faster_whisper import WhisperModel` 가 ImportError 발생 시 actionable 메시지:

```
ImportError: faster-whisper is not installed.
Install with: uv sync --extra asr
or: pip install 'tube-scout[asr]'
```

`pyproject.toml`에 `[project.optional-dependencies] asr = ["faster-whisper>=1.0.0,<2.0.0"]` 신규.

---

## 테스트 진입점

- `tests/contract/test_asr_contract.py`:
  - `test_transcribe_audio_signature_matches_contract` (시그니처 검증, 호출하지 않음)
  - `test_preset_table_has_required_keys` (4 preset, 4 keys per preset)
  - `test_caption_source_detail_format` (regex 검증)
- `tests/unit/test_asr_quality_flags.py`:
  - `test_detect_repeat_n_finds_3_consecutive`
  - `test_detect_silence_filler_finds_common_patterns` (5개 잔재 패턴)
  - `test_language_mismatch_triggers_when_detected_differs`
- `tests/integration/test_asr_with_cached_model.py` (`@pytest.mark.slow`):
  - PoC 영상 (5-1.임경민, 105초) wav 입력 → segments 출력 → quality flags 측정 검증
- `tests/integration/test_asr_importerror_actionable.py`:
  - faster-whisper 미설치 시 actionable 메시지 (mock import).
