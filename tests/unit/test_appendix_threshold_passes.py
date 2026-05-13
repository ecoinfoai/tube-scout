"""T072 RED — unit tests for passes_appendix OR semantics (spec 013 C-3 deferred)."""
import pytest


class _FakePair:
    """Minimal comparison result row stub."""

    def __init__(
        self,
        i2_cosine_similarity: float = 0.0,
        i6_longest_contiguous_seconds: float = 0.0,
        i7_distribution_dispersion: float = 0.0,
        i8_position_diversity: float = 0.0,
        audio_fp_hamming: int | None = None,
    ) -> None:
        self.i2_cosine_similarity = i2_cosine_similarity
        self.i6_longest_contiguous_seconds = i6_longest_contiguous_seconds
        self.i7_distribution_dispersion = i7_distribution_dispersion
        self.i8_position_diversity = i8_position_diversity
        self.audio_fp_hamming = audio_fp_hamming


def test_passes_appendix_or_semantics_single_axis() -> None:
    """Single threshold set — pair enters appendix if that one axis is exceeded."""
    from tube_scout.reporting.professor_nc2 import AppendixThresholds, passes_appendix

    t = AppendixThresholds(i2_cosine=0.80)
    pair_above = _FakePair(i2_cosine_similarity=0.85)
    pair_below = _FakePair(i2_cosine_similarity=0.70)
    assert passes_appendix(pair_above, t) is True
    assert passes_appendix(pair_below, t) is False


def test_passes_appendix_no_thresholds_admits_all() -> None:
    """Phase 3 30-day default — all thresholds None → every pair enters appendix."""
    from tube_scout.reporting.professor_nc2 import AppendixThresholds, passes_appendix

    t = AppendixThresholds()
    assert passes_appendix(_FakePair(), t) is True
    assert passes_appendix(_FakePair(i2_cosine_similarity=0.0, audio_fp_hamming=None), t) is True


def test_passes_appendix_5_metric_combinations() -> None:
    """All 5 axes (i2/i6/i7/i8/audio_fp) work independently via OR semantics."""
    from tube_scout.reporting.professor_nc2 import AppendixThresholds, passes_appendix

    # Only i6 threshold set — i6 above fires
    t = AppendixThresholds(i6_longest_contiguous=300.0)
    assert passes_appendix(_FakePair(i6_longest_contiguous_seconds=350.0), t) is True
    assert passes_appendix(_FakePair(i6_longest_contiguous_seconds=100.0), t) is False

    # Only i7 threshold set
    t = AppendixThresholds(i7_distribution_dispersion=0.7)
    assert passes_appendix(_FakePair(i7_distribution_dispersion=0.8), t) is True
    assert passes_appendix(_FakePair(i7_distribution_dispersion=0.5), t) is False

    # Only i8 threshold set
    t = AppendixThresholds(i8_position_diversity=0.5)
    assert passes_appendix(_FakePair(i8_position_diversity=0.6), t) is True
    assert passes_appendix(_FakePair(i8_position_diversity=0.3), t) is False

    # Only audio_fp_hamming threshold set (audio_fp_hamming=None means no audio → skip)
    t = AppendixThresholds(audio_fp_hamming=30)
    assert passes_appendix(_FakePair(audio_fp_hamming=40), t) is True
    assert passes_appendix(_FakePair(audio_fp_hamming=20), t) is False
    assert passes_appendix(_FakePair(audio_fp_hamming=None), t) is False

    # OR — multiple thresholds, any one fires
    t = AppendixThresholds(i2_cosine=0.80, audio_fp_hamming=30)
    assert passes_appendix(_FakePair(i2_cosine_similarity=0.85), t) is True
    assert passes_appendix(_FakePair(audio_fp_hamming=40), t) is True
    assert passes_appendix(_FakePair(i2_cosine_similarity=0.70, audio_fp_hamming=20), t) is False
