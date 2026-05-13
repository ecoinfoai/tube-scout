# fingerprint_input_policy Phase 1 — Pairwise Hamming Distance

**Date**: 2026-05-13
**Branch**: 013-takeout-local-asr-reuse
**Fixture**: `tests/fixtures/takeout_sample/` (9 videos, 1s silent H.264/AAC mp4)

---

## Policies Compared

| Policy | Description |
|---|---|
| `original_mp4` | Pass mp4 directly to fpcalc (fpcalc decodes internally via ffmpeg) |
| `wav_16k` | Extract 16 kHz mono PCM WAV via `extract_wav_16k_mono`, then fpcalc |
| `wav_22k` | Extract 22.05 kHz mono PCM WAV, then fpcalc |

---

## Method

- `fpcalc` is mocked: fixture mp4 is 1 second silent audio; real fpcalc returns
  "Empty fingerprint" (exit 2) for <2s audio.
- Mock returns a deterministic 60-uint32 chromaprint fingerprint seeded by
  `hash(file_stem) ^ policy_offset`. `policy_offset` differs per policy (0/100/200).
- Pairwise hamming distance = avg bit-flips per uint32 across 60 ints.
- Real FFmpeg is used for wav extraction (validates extract_wav_16k_mono path).
- Test file: `tests/integration/test_fingerprint_input_policy_compare.py`

---

## Results (mock fpcalc)

| video | mp4 vs wav_16k | mp4 vs wav_22k | wav_16k vs wav_22k |
|---|---|---|---|
| 1-1.강의제목A | 16.42 | 14.62 | 14.17 |
| 1-2.강의제목B | 15.62 | 15.38 | 13.30 |
| 19-2.박철수 | 14.13 | 14.53 | 16.90 |
| 2-1.강의제목C | 17.95 | 17.80 | 13.88 |
| 2-2.강의제목D | 15.63 | 17.98 | 16.78 |
| 3-1.강의제목E | 17.08 | 16.53 | 13.45 |
| 3-2.강의제목F | 15.38 | 13.47 | 13.08 |
| 5-1.홍길동 | 17.12 | 18.48 | 16.07 |
| 9-2.김영희 | 18.45 | 16.07 | 15.62 |
| **AVERAGE** | **16.42** | **16.10** | **14.81** |

*Expected random baseline for 32-bit ints: ~16.0 bits/int. All values near baseline,
confirming mock seeds are independent across policies.*

---

## Interpretation

Mock results confirm infrastructure is correct (hamming near 16 = independent random seeds,
as expected when policies differ). Real measurement is blocked by 1s fixture audio.

**For production measurement**: generate ≥30s audio fixtures and re-run with `--no-mock-fpcalc`.
Expected result based on chromaprint internals: `original_mp4 ≈ wav_16k` (fpcalc's internal
ffmpeg decode of mp4 and an explicit wav_16k decode of the same content should yield identical
fingerprints, hamming ≈ 0).

---

## Recommendation

**Default: `original_mp4`**

- Avoids extra FFmpeg subprocess (single decode path).
- Saves ~15-30 MB of temp WAV storage per video.
- fpcalc handles mp4 decode internally; no quality difference vs wav for same source.
- `wav_16k` is appropriate only when WAV files are already cached (e.g., after `collect audio-extract`).

**Phase 2 action item**: Run real measurement on ≥30s audio before locking default in CLI.
