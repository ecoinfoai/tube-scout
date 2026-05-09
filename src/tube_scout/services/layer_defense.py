"""4-layer defense service for spec 011 reuse scoring adjustment.

Applies Layer A (length cutoff) → B (baseline subtraction) →
D-phrase (whitelist subtraction) → C (evolution band demotion) in order.
Pure transformation; no DB writes. Persistence is the caller's responsibility.
"""

import sqlite3
from pathlib import Path

from tube_scout.models.content import ComparisonResult
from tube_scout.models.reuse_v2 import CandidatePair, LayerAttribution, MatchSpan, PolicyConfig
from tube_scout.services.baseline_corpus import subtract_baseline
from tube_scout.services.phrase_whitelist import subtract_phrase_whitelist


def filter_pair_whitelisted(
    candidates: list[CandidatePair],
    db_path: Path,
) -> list[CandidatePair]:
    """Remove candidate pairs whose comparison_results row has review_status='FALSE_POSITIVE'.

    Layer D pair-whitelist pre-filter: called before start_run so that
    already-dismissed pairs are never processed in nC2 mode.

    Args:
        candidates: CandidatePair list from generate_nc2_pairs.
        db_path: SQLite content_reuse.db path.

    Returns:
        Filtered list with FALSE_POSITIVE pairs removed.

    Raises:
        TypeError: If db_path is not a Path.
    """
    if not isinstance(db_path, Path):
        raise TypeError(f"db_path must be a Path, got {type(db_path).__name__}")

    if not candidates:
        return []

    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute(
            "SELECT source_video_id, target_video_id FROM comparison_results "
            "WHERE review_status = 'FALSE_POSITIVE'"
        ).fetchall()
    finally:
        conn.close()

    excluded: set[tuple[str, str]] = {(r[0], r[1]) for r in rows}
    return [
        c for c in candidates
        if (c.source_video_id, c.target_video_id) not in excluded
        and (c.target_video_id, c.source_video_id) not in excluded
    ]



def apply_layers(
    comparison: ComparisonResult,
    spans: list[MatchSpan],
    professor_id: str,
    db_path: Path,
    policy: PolicyConfig,
) -> tuple[ComparisonResult, list[MatchSpan]]:
    """Apply Layer A → B → D (phrase) → C in order, return updated comparison + spans.

    Side-effects: none (pure transformation; persistence happens in caller).

    Layer attribution is recorded inside ComparisonResult.layer_attribution.

    Args:
        comparison: ComparisonResult after I-6/I-7/I-8 computation.
        spans: MatchSpan list from time_axis analysis.
        professor_id: Professor pool identifier for baseline/whitelist lookups.
        db_path: SQLite content_reuse.db path.
        policy: PolicyConfig with layer thresholds.

    Returns:
        Tuple of (updated ComparisonResult, remaining MatchSpan list after filtering).

    Raises:
        TypeError: If db_path is not a Path.
    """
    if not isinstance(db_path, Path):
        raise TypeError(f"db_path must be a Path, got {type(db_path).__name__}")

    attributions: list[LayerAttribution] = list(comparison.layer_attribution)
    current_spans: list[MatchSpan] = list(spans)
    grade = comparison.grade
    excluded = False

    # Layer A: length cutoff
    i6 = comparison.i6_longest_contiguous_seconds
    if i6 is not None and i6 < policy.layer_a_min_seconds:
        attributions.append(LayerAttribution(
            layer="A",
            action="excluded",
            reason=(
                f"Longest contiguous match ({i6:.1f}s) is below "
                f"layer_a_min_seconds ({policy.layer_a_min_seconds:.1f}s)"
            ),
        ))
        excluded = True
    else:
        attributions.append(LayerAttribution(
            layer="A",
            action="no-op",
            reason=(
                f"Longest contiguous match ({i6}s) meets "
                f"layer_a_min_seconds threshold ({policy.layer_a_min_seconds:.1f}s)"
            ),
        ))

    # Layer B: baseline subtraction
    if not excluded and current_spans:
        remaining_b, sub_b = subtract_baseline(professor_id, current_spans, db_path)
        if sub_b > 0.0:
            attributions.append(LayerAttribution(
                layer="B",
                action="subtracted",
                reason=f"Subtracted {sub_b:.1f}s matching baseline phrases for {professor_id}",
            ))
            current_spans = remaining_b
        else:
            attributions.append(LayerAttribution(
                layer="B",
                action="no-op",
                reason="No baseline phrase matches found",
            ))
    else:
        attributions.append(LayerAttribution(
            layer="B",
            action="no-op",
            reason="Skipped (excluded by Layer A or no spans)",
        ))

    # Layer D-phrase: whitelist phrase subtraction
    if not excluded and current_spans:
        remaining_d, removed_count = subtract_phrase_whitelist(
            professor_id, current_spans, db_path
        )
        if removed_count > 0:
            attributions.append(LayerAttribution(
                layer="D",
                action="subtracted",
                reason=f"Removed {removed_count} span(s) matching phrase whitelist for {professor_id}",
            ))
            current_spans = remaining_d
        else:
            attributions.append(LayerAttribution(
                layer="D",
                action="no-op",
                reason="No phrase whitelist matches found",
            ))
    else:
        attributions.append(LayerAttribution(
            layer="D",
            action="no-op",
            reason="Skipped (excluded by Layer A or no spans)",
        ))

    # Layer C: evolution band demotion
    i2 = comparison.i2_cosine_similarity
    if not excluded and i2 is not None:
        low, high = policy.layer_c_evolution_band
        if low <= i2 <= high:
            attributions.append(LayerAttribution(
                layer="C",
                action="demoted",
                reason=(
                    f"Cosine {i2:.3f} falls in evolution band [{low:.2f}, {high:.2f}]; "
                    "grade demoted to moderate"
                ),
            ))
            grade = "moderate"
        else:
            attributions.append(LayerAttribution(
                layer="C",
                action="no-op",
                reason=f"Cosine {i2:.3f} outside evolution band [{low:.2f}, {high:.2f}]",
            ))
    else:
        attributions.append(LayerAttribution(
            layer="C",
            action="no-op",
            reason="Skipped (excluded by Layer A or cosine not available)",
        ))

    updated = comparison.model_copy(update={
        "layer_attribution": attributions,
        "grade": grade,
    })

    return updated, current_spans
