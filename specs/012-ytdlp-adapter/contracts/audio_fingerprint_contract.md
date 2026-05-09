# Contract: `services/audio_fingerprint.py`

Module-level contract — chromaprint fingerprint extraction (subprocess fpcalc) + Python decode + similarity helpers. **No yt-dlp / no DB** (those are in adjacent modules).

## Public surface

```python
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import numpy as np


def extract_chromaprint_fingerprint(
    audio_path: Path,
    length_seconds: int = 0,                       # 0 = full length
    timeout_seconds: float = 60.0,
) -> tuple[bytes, float]:
    """Run fpcalc subprocess, return (fp_b64_bytes, duration_seconds).

    Calls `fpcalc -length <length_seconds> <audio_path>` and parses stdout
    for `DURATION=` and `FINGERPRINT=` lines.

    Args:
        audio_path: Path to audio file (mp3 / wav / etc., fpcalc handles decode).
        length_seconds: 0 for full length, >0 for first N seconds only.
        timeout_seconds: subprocess timeout. fpcalc is fast (<1s for 33min mp3).

    Returns:
        (fingerprint_b64_ascii_bytes, duration_seconds_int_as_float).
        Example: (b"AQA-rVMSRUkiJdmEjzoq...", 1989.0)

    Raises:
        FingerprintExtractError: audio file missing, fpcalc returncode != 0,
            or stdout missing FINGERPRINT/DURATION lines.
            Message: "fpcalc failed for <path>: <stderr last line>.
            Verify ffmpeg available and audio file not corrupt."
        AudioTooShortError: duration < 30 seconds (chromaprint reliability lower bound).
            Message: "Audio <path> is <N>s; minimum 30s required for fingerprint."
        subprocess.TimeoutExpired: fpcalc hung (very rare).

    Postcondition:
        - len(fingerprint) >= 16 bytes (sanity check, RV-4)
        - duration matches ffprobe within ±1s
    """


def decode_fingerprint_to_array(fp_b64: bytes) -> "np.ndarray":
    """Decode chromaprint base64 to uint32 numpy array.

    Lazy-imports `chromaprint` (from pyacoustid PyPI) and `numpy`.

    Args:
        fp_b64: ASCII bytes from `extract_chromaprint_fingerprint()`.

    Returns:
        Shape (n_frames,), dtype uint32. ~8.07 frames/sec (chromaprint frame rate).
        For a 33-min audio: shape == (16045,).

    Raises:
        FingerprintDecodeError: chromaprint.decode_fingerprint returns empty
            or version != 1.
            Message: "chromaprint decode produced empty array; b64 may be corrupt."
    """


def hamming_distance_per_int(a: "np.ndarray", b: "np.ndarray") -> float:
    """Bit-level hamming distance averaged per uint32.

    Args:
        a, b: uint32 arrays of equal length.

    Returns:
        Mean bits-flipped per uint32 (range 0.0..32.0).

    Raises:
        ValueError: arrays have unequal length or non-uint32 dtype.

    Reference (spike-confirmed):
        - same audio → 0.0
        - different lectures → ~15-16 bits (50% random baseline)
        - reuse candidate threshold (spec Y) → < 8 bits
    """


def best_alignment_hamming(
    a: "np.ndarray",
    b: "np.ndarray",
    window_frames: int = 400,
    step: int = 4,
) -> tuple[float, int]:
    """Search ±window_frames for min hamming distance.

    Args:
        a, b: uint32 fingerprint arrays (different lengths OK).
        window_frames: ±N frames offset search range. 400 = ±50 sec at 8 fps.
        step: offset increment (smaller = finer search, slower).

    Returns:
        (min_hamming_per_int, best_offset_frames).
        Negative offset = b is shifted later than a; positive = a is shifted later.

    Postcondition:
        - min_hamming <= hamming_distance_per_int(a[:n], b[:n]) for any n trim
        - best_offset in [-window_frames, +window_frames]
    """
```

## Internal helpers (private)

```python
def _parse_fpcalc_stdout(stdout: str) -> tuple[bytes, float]:
    """Extract DURATION + FINGERPRINT lines from fpcalc stdout.

    Regex (line-anchored): r"^DURATION=(\d+)$" + r"^FINGERPRINT=(\S+)$"
    """


def _verify_fingerprint_sanity(fp_b64: bytes) -> None:
    """Validate b64 length >= 16 bytes (RV-4)."""
```

## Test scenarios (RED-first)

`tests/unit/test_audio_fingerprint.py` — 9 시나리오:

1. **Extract from spike fixture mp3**: `tuxscjwiJYs.mp3` (33min, 22050Hz mono) → returns (b"AQA...", 1989.0). subprocess call args 검증.
2. **Extract from too-short audio**: 25s mp3 → raises `AudioTooShortError`.
3. **Extract with fpcalc returncode != 0**: subprocess mock returncode=1, stderr="ERROR: ..." → raises `FingerprintExtractError` with stderr 마지막 줄 포함.
4. **Extract with malformed stdout**: stdout="garbage\n" → raises `FingerprintExtractError`.
5. **Decode b64 to uint32 array**: spike fixture fp_test1.txt 의 FINGERPRINT 값 → shape (16045,), dtype uint32.
6. **Hamming distance — self**: arr ^ arr → 0.0.
7. **Hamming distance — shifted**: `np.roll(arr, 100)` → ~14.5 bits (spike 측정).
8. **Best alignment — same array**: best_alignment(arr, arr) → (0.0, 0).
9. **Best alignment — V1 vs V2**: spike fixtures fp_test1 + fp_test2 → ~15.0 bits @ offset +288 frames (spike 측정 정확 일치).

`tests/integration/test_audio_fingerprint_flow.py` — 통합 시나리오:

1. **Full lifecycle**: yt-dlp mock으로 mp3 fixture → `extract_chromaprint_fingerprint()` → DB INSERT → 음원 파일 unlink → DB SELECT 결과 검증.
2. **30s 미만 영상 skip**: fixture 25s mp3 → audit-log "too_short" + DB INSERT 0건 + 음원 즉시 삭제.
3. **Idempotent re-run**: 동일 video_id 재처리 → audit "skip_existing" + DB INSERT 0건.
4. **`--force` 시 덮어쓰기**: 동일 video_id + `--force` → DB UPDATE (extracted_at 갱신) + 음원 즉시 삭제.

## NixOS LD requirements

이 모듈은 `chromaprint` Python module import 시 다음 LD 가용 필요 (B-X1-8):
- `libchromaprint.so` (chromaprint 1.6.0+)
- `libstdc++.so.6` (numpy c-ext)
- `libz.so.1` (numpy 일부)

dev-squad는 `flake.nix shellHook` 의 `LD_LIBRARY_PATH` 자동 export로 해결. 모듈 단위 lazy import + ImportError 시 actionable 메시지 ("Install chromaprint via `nix develop` and ensure libchromaprint.so is in LD_LIBRARY_PATH.").

## Boundary references

- B-X1-2: `extract_chromaprint_fingerprint()` 결과는 `storage/content_db.py:insert_audio_fingerprint()` 가 영속 (별도 모듈)
- B-X1-3: `decode_fingerprint_to_array()` + `hamming_distance_per_int()` + `best_alignment_hamming()` 의 시그니처는 spec Y(미래) read-only consume — 동결
- B-X1-8: NixOS LD_LIBRARY_PATH 의존성 (위 참조)
- B-X1-9: 텍스트 fingerprint(`services/fingerprint.py`)와 별도 모듈, 클래스 이름 충돌 0
- Constitution II: 모든 raise 사이트 actionable English
