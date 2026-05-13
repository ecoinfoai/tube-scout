# Measurement: audio_fp_hamming Threshold (Phase 3)

**Status**: PENDING — run `pytest tests/integration/test_audio_fp_hamming_distribution.py -m slow` with real PoC videos.

**Purpose**: Determine the cutoff value for `audio_fp_hamming_threshold` in
`pattern_classifier.classify()`, used to detect `RE_RECORDED_SAME_CONTENT` pairs.

## Background

`audio_fp_hamming` is the Hamming distance between two videos' Chromaprint fingerprints.
Lower Hamming distance = more similar audio.

The `classify()` function uses this threshold:
- `audio_fp_hamming > threshold` → audio is "different" enough to flag as re-recorded.
- Default: 50 (start point before measurement).

## Methodology

### Pair categories
| Category | Description | Expected Hamming |
|----------|-------------|-----------------|
| **Same audio** | Same mp4 re-encoded (ffmpeg bit-exact or lossy re-encode) | Low (0–20) |
| **Different audio** | Different lecture videos from same course | High (100–300+) |
| **Slightly modified** | Same lecture with intro/outro trimmed | Medium (20–80) |

### Dataset (PoC — 9 videos from takeout_sample)
- 9 mp4 files: `tests/fixtures/takeout_sample/Takeout/YouTube 및 YouTube Music/동영상/`
- C(9,2) = 36 pairs → measure all 36 Hamming distances.

### Procedure
1. Run `fpcalc` on all 9 mp4 files → get Chromaprint fingerprints.
2. Compute Hamming distance for all 36 pairs.
3. Plot distribution; identify natural gap between "same-ish" and "different".

## Results

*(To be filled in after running measurement)*

| Pair | Hamming Distance | Category |
|------|-----------------|----------|
| TBD | TBD | TBD |

### Recommended Threshold

**TBD** — set `audio_fp_hamming_threshold = <value>` based on:
- All "same audio" pairs below threshold.
- All "different audio" pairs above threshold.
- Allow ~10 Hamming units margin.

## Implementation

After measurement, update `pattern_classifier.classify()`:
```python
def classify(..., audio_fp_hamming_threshold: int = <measured_value>):
```

## Reference

- Default value: 50 (conservative start point, unvalidated).
- Chromaprint specification: fingerprints are 32-bit integers; Hamming distance max = 32.
  For full Chromaprint byte arrays, max Hamming ≈ 4096 bits.
