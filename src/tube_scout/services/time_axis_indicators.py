"""Time-axis indicators service for spec 011 US2.

Computes I-6 (longest contiguous match), I-7 (span length dispersion),
and I-8 (positional diversity across early/middle/late thirds) using
a greedy segment-alignment algorithm (research.md R-2).
"""

import math
from typing import Any, Callable

from tube_scout.models.reuse_v2 import CandidatePair, MatchSpan, TimeAxisResult
from tube_scout.services.phrase_whitelist import normalize_phrase


def find_match_spans(
    captions_a: list[dict[str, Any]],
    captions_b: list[dict[str, Any]],
    normalize: Callable[[str], str] = normalize_phrase,
) -> list[MatchSpan]:
    """Find aligned match spans using normalized exact match + greedy extension.

    Algorithm (research.md R-2):
    1. Normalize both segment texts via the ``normalize`` callback.
    2. For each segment in A, find the earliest unconsumed matching segment
       in B with the same normalized text — anchor.
    3. From each anchor, extend leftward and rightward as long as
       consecutive segment pairs continue to match.
    4. Emit a MatchSpan per maximal extension, mark consumed segments,
       continue scanning forward.

    Returns spans sorted by (start_a_seconds ascending).

    Args:
        captions_a: Caption segments for video A. Each dict must have
            'start', 'end', and 'text' keys.
        captions_b: Caption segments for video B. Same schema.
        normalize: Text normalization callable. Defaults to normalize_phrase
            (single source of truth — research.md R-7).

    Returns:
        List of MatchSpan sorted by start_a_seconds ascending.

    Raises:
        ValueError: If any segment is missing required keys.
    """
    for seg in captions_a + captions_b:
        if "start" not in seg or "end" not in seg or "text" not in seg:
            raise ValueError(
                f"Each caption segment must have 'start', 'end', and 'text' keys; "
                f"got {list(seg.keys())}"
            )

    # Pre-normalize all texts
    norm_a = [normalize(s["text"]) for s in captions_a]
    norm_b = [normalize(s["text"]) for s in captions_b]

    # Build index: normalized_text -> list of B indices (in order)
    from collections import defaultdict
    b_index: dict[str, list[int]] = defaultdict(list)
    for j, txt in enumerate(norm_b):
        if txt:
            b_index[txt].append(j)

    consumed_a: set[int] = set()
    consumed_b: set[int] = set()
    spans: list[MatchSpan] = []

    for i, txt_a in enumerate(norm_a):
        if i in consumed_a or not txt_a:
            continue

        candidates = b_index.get(txt_a, [])
        anchor_j: int | None = None
        for j in candidates:
            if j not in consumed_b:
                anchor_j = j
                break

        if anchor_j is None:
            continue

        # Extend leftward from (i, anchor_j)
        left_a = i
        left_b = anchor_j
        while (
            left_a - 1 >= 0
            and left_b - 1 >= 0
            and (left_a - 1) not in consumed_a
            and (left_b - 1) not in consumed_b
            and norm_a[left_a - 1] == norm_b[left_b - 1]
            and norm_a[left_a - 1]
        ):
            left_a -= 1
            left_b -= 1

        # Extend rightward from (i, anchor_j)
        right_a = i
        right_b = anchor_j
        while (
            right_a + 1 < len(norm_a)
            and right_b + 1 < len(norm_b)
            and (right_a + 1) not in consumed_a
            and (right_b + 1) not in consumed_b
            and norm_a[right_a + 1] == norm_b[right_b + 1]
            and norm_a[right_a + 1]
        ):
            right_a += 1
            right_b += 1

        # Mark consumed
        for idx in range(left_a, right_a + 1):
            consumed_a.add(idx)
        for idx in range(left_b, right_b + 1):
            consumed_b.add(idx)

        start_a = float(captions_a[left_a]["start"])
        end_a = float(captions_a[right_a]["end"])
        start_b = float(captions_b[left_b]["start"])
        end_b = float(captions_b[right_b]["end"])
        length_s = end_a - start_a

        # Ensure end > start (guard against degenerate segments)
        if end_a <= start_a or end_b <= start_b:
            continue

        sample = captions_a[left_a]["text"][:80]
        spans.append(
            MatchSpan(
                start_a_seconds=start_a,
                end_a_seconds=end_a,
                start_b_seconds=start_b,
                end_b_seconds=end_b,
                length_seconds=length_s,
                matched_text_sample=sample,
            )
        )

    spans.sort(key=lambda s: s.start_a_seconds)
    return spans


def compute_time_axis(
    pair: CandidatePair,
    captions_a: list[dict[str, Any]],
    captions_b: list[dict[str, Any]],
) -> TimeAxisResult:
    """Compute I-6 / I-7 / I-8 + spans for a candidate pair.

    Uses find_match_spans then derives:
    - I-6 = max(span.length_seconds) or 0.0 if no spans.
    - I-7 = stdev(span.length_seconds); 0.0 if fewer than 2 spans.
    - I-8 = positional spread across early/middle/late thirds of the
      shorter video, normalized 0~1 (0 = all in one third, 1 = uniformly spread).

    Args:
        pair: Candidate pair after cosine cull.
        captions_a: Caption segments for video A.
        captions_b: Caption segments for video B.

    Returns:
        TimeAxisResult with i6/i7/i8 values and span list.

    Raises:
        ValueError: If captions_a or captions_b are empty.
    """
    if not captions_a:
        raise ValueError(
            f"captions_a is empty for video '{pair.source_video_id}'. "
            "Ensure captions were collected before running time-axis analysis."
        )
    if not captions_b:
        raise ValueError(
            f"captions_b is empty for video '{pair.target_video_id}'. "
            "Ensure captions were collected before running time-axis analysis."
        )

    spans = find_match_spans(captions_a, captions_b, normalize=normalize_phrase)

    if not spans:
        return TimeAxisResult(
            i6_longest_contiguous_seconds=0.0,
            i7_distribution_dispersion=0.0,
            i8_position_diversity=0.0,
            spans=[],
        )

    lengths = [s.length_seconds for s in spans]

    # I-6: longest span
    i6 = max(lengths)

    # I-7: standard deviation of span lengths (0 if < 2 spans)
    if len(lengths) < 2:
        i7 = 0.0
    else:
        mean = sum(lengths) / len(lengths)
        variance = sum((x - mean) ** 2 for x in lengths) / len(lengths)
        i7 = math.sqrt(variance)

    # I-8: positional diversity across early/middle/late thirds of shorter video
    dur_a = float(captions_a[-1]["end"]) if captions_a else 0.0
    dur_b = float(captions_b[-1]["end"]) if captions_b else 0.0
    shorter_dur = min(dur_a, dur_b)

    if shorter_dur <= 0.0:
        i8 = 0.0
    else:
        third = shorter_dur / 3.0
        thirds_hit: set[int] = set()
        for s in spans:
            mid = (s.start_a_seconds + s.end_a_seconds) / 2.0
            thirds_hit.add(min(2, int(mid / third)))
        # 0 = all in one third, 1 = all three thirds covered
        i8 = (len(thirds_hit) - 1) / 2.0

    return TimeAxisResult(
        i6_longest_contiguous_seconds=i6,
        i7_distribution_dispersion=i7,
        i8_position_diversity=i8,
        spans=spans,
    )
