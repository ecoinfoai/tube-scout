"""Pydantic v2 models for spec 011 full-stack subtitle reuse detection.

All models are immutable (frozen=True) unless noted. Import these into
service-layer code; never bypass validation by constructing dicts directly.
"""

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class ReusePatternLabel(str, Enum):
    """Four-way classification of a reuse pair by contiguity and week alignment.

    Values:
        WHOLE_SAME_WEEK: Single contiguous block reused within the same week.
        SCATTERED_SAME_WEEK: Multiple short spans reused within the same week.
        WHOLE_DIFF_WEEK: Single contiguous block reused across different weeks.
        SCATTERED_DIFF_WEEK: Multiple short spans reused across different weeks.
    """

    WHOLE_SAME_WEEK = "whole-same-week"
    SCATTERED_SAME_WEEK = "scattered-same-week"
    WHOLE_DIFF_WEEK = "whole-different-week"
    SCATTERED_DIFF_WEEK = "scattered-different-week"


class LayerAttribution(BaseModel):
    """Records how a single defense layer acted on a comparison pair.

    Attributes:
        layer: Which layer acted (A=length, B=baseline, C=evolution, D=whitelist).
        action: Effect applied by the layer.
        reason: English actionable explanation of why the action was taken.
    """

    model_config = {"frozen": True}

    layer: Literal["A", "B", "C", "D"]
    action: Literal["excluded", "demoted", "subtracted", "no-op"]
    reason: str


class MatchSpan(BaseModel):
    """A single contiguous segment of identical caption text between two videos.

    Attributes:
        start_a_seconds: Start time in video A (seconds).
        end_a_seconds: End time in video A (seconds).
        start_b_seconds: Start time in video B (seconds).
        end_b_seconds: End time in video B (seconds).
        length_seconds: Duration of the matching span (video A reference).
        matched_text_sample: Short sample of the matched text (50-100 chars).
        baseline_subtracted: True if Layer B removed this span from the score.
        whitelisted: True if Layer D phrase whitelist removed this span.
    """

    model_config = {"frozen": True}

    start_a_seconds: float = Field(..., ge=0.0)
    end_a_seconds: float = Field(..., ge=0.0)
    start_b_seconds: float = Field(..., ge=0.0)
    end_b_seconds: float = Field(..., ge=0.0)
    length_seconds: float = Field(..., ge=0.0)
    matched_text_sample: str
    baseline_subtracted: bool = False
    whitelisted: bool = False

    @model_validator(mode="after")
    def _end_after_start(self) -> "MatchSpan":
        if self.end_a_seconds <= self.start_a_seconds:
            raise ValueError(
                f"end_a_seconds ({self.end_a_seconds}) must be > start_a_seconds ({self.start_a_seconds})"
            )
        if self.end_b_seconds <= self.start_b_seconds:
            raise ValueError(
                f"end_b_seconds ({self.end_b_seconds}) must be > start_b_seconds ({self.start_b_seconds})"
            )
        return self


class VideoRef(BaseModel):
    """Reference to a single video within a channel/author context.

    Attributes:
        channel_alias: spec 003 channel alias.
        video_id: Video identifier (synthetic in tests).
        author_marker: parsed_titles professor field or '__channel_owner__'.
    """

    model_config = {"frozen": True}

    channel_alias: str
    video_id: str
    author_marker: str


class VideoPairRef(BaseModel):
    """A pair of video references yielded by the checkpoint iterator.

    Attributes:
        source_video_id: First video in the pair.
        target_video_id: Second video in the pair.
        professor_id: Professor pool this pair belongs to.
    """

    model_config = {"frozen": True}

    source_video_id: str
    target_video_id: str
    professor_id: str


class CaptionPool(BaseModel):
    """All videos belonging to one professor across potentially multiple channels.

    Attributes:
        professor_id: Professor identifier (e.g. 'prof-park-jc').
        video_refs: Ordered list of video references in this pool.
    """

    model_config = {"frozen": True}

    professor_id: str
    video_refs: list[VideoRef]


class BaselinePhrase(BaseModel):
    """A stylistic phrase associated with a professor's habitual speech patterns.

    Attributes:
        professor_id: Professor the phrase belongs to.
        phrase_normalized: R-7 normalized form used for matching.
        phrase_raw: Original text as registered (for display and audit).
        occurrences: Number of videos this phrase appeared in.
        source_video_ids: Video IDs that contributed to this phrase.
        seeded: True if added by bootstrap, False if added manually by admin.
    """

    model_config = {"frozen": True}

    professor_id: str
    phrase_normalized: str
    phrase_raw: str
    occurrences: int = Field(..., ge=1)
    source_video_ids: list[str]
    seeded: bool


class WhitelistPairEntry(BaseModel):
    """An admin-declared pair that should be excluded from reuse scoring.

    Attributes:
        source_video_id: First video of the pair.
        target_video_id: Second video of the pair.
        professor_id: Scoped professor (None = global pair exclusion).
        reason: Admin explanation for the exclusion.
        admin: Identifier of the admin who registered this entry.
        registered_at: UTC timestamp of registration.
    """

    model_config = {"frozen": True}

    source_video_id: str
    target_video_id: str
    professor_id: str | None = None
    reason: str
    admin: str
    registered_at: datetime


class WhitelistPhraseEntry(BaseModel):
    """An admin-declared phrase whose matches are excluded from scoring.

    Attributes:
        professor_id: Professor scope for this whitelist entry.
        phrase_normalized: R-7 normalized form used for matching.
        phrase_raw: Original text for display and audit.
        reason: Admin explanation for the exclusion.
        admin: Identifier of the admin who registered this entry.
        registered_at: UTC timestamp of registration.
    """

    model_config = {"frozen": True}

    professor_id: str
    phrase_normalized: str
    phrase_raw: str
    reason: str
    admin: str
    registered_at: datetime


class WhitelistView(BaseModel):
    """Aggregated view of all whitelist entries for a professor or project.

    Attributes:
        pair_entries: All pair-level whitelist entries.
        phrase_entries: All phrase-level whitelist entries.
    """

    model_config = {"frozen": True}

    pair_entries: list[WhitelistPairEntry] = Field(default_factory=list)
    phrase_entries: list[WhitelistPhraseEntry] = Field(default_factory=list)


class PairCheckpoint(BaseModel):
    """Progress metadata for an nC2 pair analysis run (resume support).

    Attributes:
        run_id: Unique run identifier (e.g. 'nc2-prof-park-jc-20260601-2300').
        professor_id: Professor whose pool is being analysed.
        matching_mode: Analysis mode used for this run.
        pair_count_total: Total pairs to process.
        pair_count_done: Pairs processed so far.
        started_at: UTC timestamp when the run began.
        last_pair_at: UTC timestamp of the last completed pair (None if none done).
        status: Current run lifecycle state.
    """

    model_config = {"frozen": True}

    run_id: str
    professor_id: str
    matching_mode: Literal["M-default", "M-nC2"]
    pair_count_total: int = Field(..., ge=0)
    pair_count_done: int = Field(..., ge=0)
    started_at: datetime
    last_pair_at: datetime | None = None
    status: Literal["in_progress", "completed", "aborted"]


class PolicyConfig(BaseModel):
    """Project-level policy thresholds loaded from policy.yaml.

    Attributes:
        layer_a_min_seconds: Minimum contiguous match length to clear Layer A.
        layer_c_evolution_band: (low, high) cosine band that demotes to moderate.
        matching_cosine_cull: Cosine threshold for the 1st-pass candidate filter.
        pattern_whole_threshold_ratio: I-6/min_duration ratio for whole vs scattered.
        composite_weights: Per-indicator weights (i1..i8) summing to 1.0 ± 0.01.
    """

    model_config = {"frozen": True}

    layer_a_min_seconds: float = Field(default=60.0, gt=0.0)
    layer_c_evolution_band: tuple[float, float] = (0.60, 0.75)
    matching_cosine_cull: float = Field(default=0.55, ge=0.0, le=1.0)
    pattern_whole_threshold_ratio: float = Field(default=0.50, gt=0.0, lt=1.0)
    composite_weights: dict[str, float] = Field(
        default_factory=lambda: {
            "i1": 0.20, "i2": 0.20, "i3": 0.10, "i4": 0.05,
            "i5": 0.05, "i6": 0.20, "i7": 0.10, "i8": 0.10,
        }
    )

    @field_validator("layer_c_evolution_band")
    @classmethod
    def _band_valid(cls, v: tuple[float, float]) -> tuple[float, float]:
        low, high = v
        if not (0.0 <= low < high <= 1.0):
            raise ValueError(
                f"layer_c_evolution_band must satisfy 0 <= low < high <= 1, got {v}"
            )
        return v

    @model_validator(mode="after")
    def _weights_sum_to_one(self) -> "PolicyConfig":
        total = sum(self.composite_weights.values())
        if abs(total - 1.0) > 0.01:
            raise ValueError(
                f"composite_weights must sum to 1.0 ± 0.01, got {total:.4f}"
            )
        return self


class CandidatePair(BaseModel):
    """A video pair that passed the cosine cull threshold and awaits full analysis.

    Attributes:
        source_video_id: First video ID.
        target_video_id: Second video ID.
        cosine: Cosine similarity score that cleared the cull threshold.
        professor_id: Professor pool this pair belongs to.
    """

    model_config = {"frozen": True}

    source_video_id: str
    target_video_id: str
    cosine: float = Field(..., ge=0.0, le=1.0)
    professor_id: str


class TimeAxisResult(BaseModel):
    """Computed time-axis indicators for a candidate pair.

    Attributes:
        i6_longest_contiguous_seconds: I-6: length of the longest matching span.
        i7_distribution_dispersion: I-7: dispersion of span lengths (stdev-based).
        i8_position_diversity: I-8: spread across early/middle/late timeline thirds.
        spans: All matching spans found by segment alignment.
    """

    model_config = {"frozen": True}

    i6_longest_contiguous_seconds: float = Field(..., ge=0.0)
    i7_distribution_dispersion: float = Field(..., ge=0.0)
    i8_position_diversity: float = Field(..., ge=0.0, le=1.0)
    spans: list[MatchSpan]


class ProfessorMapping(BaseModel):
    """A registration linking a channel/author combination to a professor pool.

    Attributes:
        professor_id: Destination professor pool identifier.
        display_name: Human-readable name for the professor.
        channel_alias: spec 003 channel alias.
        author_marker: Video author field or '__channel_owner__'.
        registered_at: UTC timestamp of registration.
        registered_by: Admin identifier who created this mapping.
        notes: Optional free-text notes.
    """

    model_config = {"frozen": True}

    professor_id: str
    display_name: str
    channel_alias: str
    author_marker: str
    registered_at: datetime
    registered_by: str
    notes: str | None = None


class BaselineBootstrapReport(BaseModel):
    """Summary of an automatic baseline bootstrap run for a professor.

    Attributes:
        professor_id: Professor whose corpus was bootstrapped.
        phrases_added: Number of phrases seeded into baseline_corpus.
        phrases_skipped: Number of candidates rejected (below occurrence threshold).
        sample_phrases: Up to 5 sample phrases that were added (for admin review).
    """

    model_config = {"frozen": True}

    professor_id: str
    phrases_added: int = Field(..., ge=0)
    phrases_skipped: int = Field(..., ge=0)
    sample_phrases: list[str]
