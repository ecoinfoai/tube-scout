"""T071 RED — contract tests for reporting/professor_nc2.py."""
import inspect
from datetime import datetime


def test_render_professor_nc2_report_signature_matches_contract() -> None:
    """render_professor_nc2_report signature matches contract: 9 params, correct defaults."""
    from tube_scout.reporting.professor_nc2 import render_professor_nc2_report

    sig = inspect.signature(render_professor_nc2_report)
    params = list(sig.parameters.keys())
    assert "professor" in params
    assert "channel_alias" in params
    assert "db" in params
    assert "output_dir" in params
    assert "matching_mode" in params
    assert "top_k" in params
    assert "sort_by" in params
    assert "appendix_thresholds" in params
    assert "output_format" in params

    assert sig.parameters["matching_mode"].default == "M-nC2"
    assert sig.parameters["top_k"].default == 50
    assert sig.parameters["sort_by"].default == "i2-cosine"
    assert sig.parameters["output_format"].default == "both"


def test_report_result_includes_pattern_distribution() -> None:
    """ReportResult has all required fields including pattern_distribution dict."""
    from tube_scout.reporting.professor_nc2 import AppendixThresholds, ReportResult

    result = ReportResult(
        professor="test-prof",
        channel_alias="test-channel",
        html_path=None,
        pdf_path=None,
        pair_count=10,
        top_k_count=10,
        appendix_count=5,
        pattern_distribution={"WHOLE_COPY": 2, "PARTIAL_COPY": 3},
        generated_at=datetime(2026, 1, 1, 0, 0, 0),
    )
    assert result.professor == "test-prof"
    assert result.pair_count == 10
    assert result.pattern_distribution == {"WHOLE_COPY": 2, "PARTIAL_COPY": 3}

    # AppendixThresholds defaults all None
    t = AppendixThresholds()
    assert t.i2_cosine is None
    assert t.i6_longest_contiguous is None
    assert t.i7_distribution_dispersion is None
    assert t.i8_position_diversity is None
    assert t.audio_fp_hamming is None
