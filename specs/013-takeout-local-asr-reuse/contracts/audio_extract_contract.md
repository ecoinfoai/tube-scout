# Contract: services/audio_extract.py

**Module**: `src/tube_scout/services/audio_extract.py` (신규)
**Spec FR mapping**: FR-010~FR-012.
**Boundary**: B-12 (flake.nix `ffmpeg`).

---

## 함수 시그니처

```python
from pathlib import Path

def extract_wav_16k_mono(
    mp4_path: Path,
    wav_path: Path,
    *,
    sample_rate: int = 16000,
    codec: str = "pcm_s16le",
    force: bool = False,
) -> Path:
    """Extract mono 16 kHz WAV from mp4 via ffmpeg subprocess.

    Args:
        mp4_path: 입력 mp4 절대 경로.
        wav_path: 출력 wav 경로 (디렉터리는 사전 생성 가정).
        sample_rate: 16000 (faster-whisper 권장). 22050 등은 호출자 책임.
        codec: pcm_s16le (기본) 또는 flac.
        force: True 시 기존 wav 덮어쓰기. False 시 기존 wav 존재하면 skip.

    Returns:
        wav_path (호출자 편의).

    Raises:
        FileNotFoundError: mp4_path 부재.
        RuntimeError: ffmpeg 종료 코드 ≠ 0 (stderr 일부를 message에 포함).
    """
```

내부 ffmpeg 호출:

```bash
ffmpeg -y -i <mp4_path> -vn -ac 1 -ar <sample_rate> -c:a <codec> <wav_path>
```

`-y`는 force=True 시만, force=False면 기존 파일 검사 후 skip.

---

## Idempotency

- `wav_path.exists() AND not force` → no-op, return wav_path.
- ffmpeg 호출은 멱등 (같은 입력은 같은 출력).

---

## Lifecycle helper

```python
def cleanup_wav(wav_path: Path, *, keep: bool = False) -> None:
    """Delete WAV unless keep=True. Safe to call when file is absent.

    Args:
        wav_path: 삭제 대상.
        keep: True 시 no-op (CLI --keep-audio 매핑).
    """

class WavLifecycle:
    """Context manager for integrated mode WAV (try/finally cleanup).

    Usage:
        with WavLifecycle(mp4_path, wav_dir, video_id, keep=False) as wav_path:
            extract_chromaprint_fingerprint(wav_path)
            transcribe_audio(wav_path, ...)
        # __exit__ deletes wav_path unless keep=True
    """
```

`WavLifecycle.__exit__` 는 SIGINT/SIGTERM에 의한 KeyboardInterrupt 발생 시에도 삭제 수행(audit "interrupted_audio_cleanup" 추가). spec 012 `build_signal_handler` 패턴 재사용.

---

## 테스트 진입점

- `tests/contract/test_audio_extract_contract.py`:
  - `test_extract_wav_16k_mono_creates_file_with_correct_specs` (sample_rate / channels / codec 검증 — ffprobe)
  - `test_extract_force_overwrite` (기존 wav 덮어씀)
  - `test_extract_no_force_skip_existing` (기존 wav 변경 0)
  - `test_extract_raises_on_missing_mp4`
  - `test_extract_raises_on_ffmpeg_failure` (가짜 mp4 입력)
  - `test_wav_lifecycle_deletes_on_normal_exit`
  - `test_wav_lifecycle_deletes_on_sigint` (KeyboardInterrupt 시뮬레이션)
  - `test_wav_lifecycle_preserves_when_keep_true`

---

## 음원 지문 통합 사용 패턴

`cli/collect.py` integrated mode (`process-audio`) 의사코드:

```python
for video in selected_videos:
    with WavLifecycle(mp4_path, cache_dir, video.video_id, keep=keep_audio) as wav_path:
        if not skip_fingerprint:
            extract_chromaprint_fingerprint(wav_path)
            insert_audio_fingerprint(db_path, video.video_id, ...)
        if not skip_asr:
            transcribe_audio_with_faster_whisper(wav_path, ...)
            write_transcript_json(transcript_path, ...)
            if auto_normalize:
                normalize_transcript(...)
```

`try/finally` 보장 — 어떤 단계가 실패해도 WAV 삭제.
