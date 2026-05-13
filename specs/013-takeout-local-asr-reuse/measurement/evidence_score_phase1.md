# evidence_score Phase 1 Measurement

Date: 2026-05-14  
Fixture: tests/fixtures/takeout_sample/Takeout (9 videos, sanitized)  
Thresholds: high=65, medium=40

## Score Distribution (per mp4)

| mp4 | video_id | score | confidence |
|-----|----------|-------|------------|
| 1-1.강의제목A.mp4 | aaaaaaaaaaa | 40 | medium |
| 1-2.강의제목B.mp4 | bbbbbbbbbbb | 40 | medium |
| 19-2.박철수.mp4 | iiiiiiiiiii | 40 | medium |
| 2-1.강의제목C.mp4 | ccccccccccc | 40 | medium |
| 2-2.강의제목D.mp4 | ddddddddddd | 40 | medium |
| 3-1.강의제목E.mp4 | eeeeeeeeeee | 40 | medium |
| 3-2.강의제목F.mp4 | fffffffffff | 40 | medium |
| 5-1.홍길동.mp4 | ggggggggggg | 45 | medium |
| 9-2.김영희.mp4 | hhhhhhhhhhh | 40 | medium |

## Summary

| bucket | count | % |
|--------|-------|---|
| high | 0 | 0% |
| medium | 9 | 100% |
| ambiguous | 0 | 0% |
| unmapped | 0 | 0% |
| **automation rate** | **9/9** | **100%** |

## Signal Breakdown

- **exact_title_match (+40)**: 9/9 fired. mp4 stem == video title exactly.
- **normalized_title_match (+30)**: 0 fired (exact match takes precedence).
- **duration_match_within_1s (+25)**: 0 fired.
  - mp4 actual duration: 1.0s (test pattern, ffprobe mock)
  - CSV metadata duration: 105s–3600s (intentional mismatch per fixture README)
  - On real Takeout data this signal should fire for most videos.
- **size_ratio_plausible (+5)**: 1 fired (5-1.홍길동.mp4, score=45 vs 40 for others)
  - mp4 test files are tiny (~few kB) — most fail the 0.5 MB/s floor check
  - On real Takeout data (100 MB+ lecture mp4s) this signal will fire reliably
- **mtime_match_within_1d (+5)**: 0 fired (fixture mtime = extraction time, created_at = 2026-04-xx)

## mtime Signal Contribution

With real Takeout data where mtime is preserved (e.g., from original recording host):
- If mtime matches created_at within 1 day: +5 → most videos reach 70+ (high)
- If mtime is corrupted (copy, external disk): +0 → stays at medium (40–45)

On the sanitized fixture, mtime = file extraction time (not original creation date),
so mtime_match=False for all 9. This is the expected degraded case.

## Threshold Tuning Recommendation

Current thresholds: high=65, medium=40. Recommendation after Phase 1:

- **No change to thresholds** for now. 100% automation (medium) is sufficient for
  Phase 1 operator-review workflow.
- **Post-Phase 1 (real Takeout data)**: if duration+size signals fire as expected,
  most videos should score 40+25+5 = 70 (high). Re-measure then.
- mtime_match is unreliable (external disk/copy risk, +5 only). Keep as-is.
- Consider lowering high_threshold to 60 if real data shows duration_match fires
  but mtime consistently fails. This would capture exact+duration+size = 40+25+5=70 → still high.

## Fixture Note

Fixture mp4 files are 1-second silent test patterns. Duration mismatch is intentional
(see tests/fixtures/takeout_sample/README.md §Notes). Real lecture mp4s will have
durations matching the metadata CSV values, enabling the +25 duration signal.
