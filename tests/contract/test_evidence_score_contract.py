"""Contract tests — evidence_score service signatures (spec 013 T027 RED).

FR-003, FR-004: score_mp4_candidates, decide_mapping, EvidenceSignals, MappingDecision.
Module does not exist yet — all tests should fail at import.
"""

from __future__ import annotations

import inspect
from pathlib import Path


def test_score_mp4_candidates_returns_per_candidate_signals(tmp_path: Path) -> None:
    """score_mp4_candidates returns one (video_id, EvidenceSignals) per candidate."""
    from tube_scout.services.evidence_score import (
        EvidenceSignals,
        score_mp4_candidates,
    )
    from tube_scout.models.content import VideoMetadata

    mp4 = tmp_path / "1-1.강의제목A.mp4"
    mp4.write_bytes(b"\x00" * 1024)

    import datetime

    now = datetime.datetime.now(tz=datetime.timezone.utc)
    # Two candidate VideoMetadata entries
    candidates = [
        VideoMetadata(
            video_id="vid001",
            title="1-1.강의제목A",
            duration_seconds=3600.0,
            channel_id="UCfake0001",
            privacy_status="unlisted",
            created_at=datetime.datetime(2026, 4, 1, 9, 0, 0, tzinfo=datetime.timezone.utc),
            source="takeout",
            ingested_at=now,
        ),
        VideoMetadata(
            video_id="vid002",
            title="1-2.강의제목B",
            duration_seconds=2700.0,
            channel_id="UCfake0001",
            privacy_status="unlisted",
            created_at=datetime.datetime(2026, 4, 8, 9, 0, 0, tzinfo=datetime.timezone.utc),
            source="takeout",
            ingested_at=now,
        ),
    ]

    result = score_mp4_candidates(mp4, candidates)

    assert isinstance(result, list), "Must return a list"
    assert len(result) == 2, f"Expected 2 results (one per candidate), got {len(result)}"
    for video_id, signals in result:
        assert isinstance(video_id, str), f"video_id must be str, got {type(video_id)}"
        assert isinstance(signals, EvidenceSignals), (
            f"signals must be EvidenceSignals, got {type(signals)}"
        )


def test_decide_mapping_signature(tmp_path: Path) -> None:
    """decide_mapping exists with correct parameters and returns a MappingDecision."""
    from tube_scout.services.evidence_score import (
        MappingDecision,
        decide_mapping,
    )

    sig = inspect.signature(decide_mapping)
    params = list(sig.parameters)
    assert "mp4_path" in params, f"decide_mapping missing mp4_path, got {params}"
    assert "video_meta_list" in params, f"decide_mapping missing video_meta_list, got {params}"
    assert "high_threshold" in params, f"decide_mapping missing high_threshold, got {params}"
    assert "medium_threshold" in params, f"decide_mapping missing medium_threshold, got {params}"

    # Verify high_threshold and medium_threshold have defaults
    assert sig.parameters["high_threshold"].default != inspect.Parameter.empty, (
        "high_threshold must have a default value"
    )
    assert sig.parameters["medium_threshold"].default != inspect.Parameter.empty, (
        "medium_threshold must have a default value"
    )

    # Verify MappingDecision has required fields
    decision_fields = MappingDecision.model_fields
    for field in ("mp4_path", "video_id", "score", "confidence", "signals", "candidates"):
        assert field in decision_fields, (
            f"MappingDecision missing field '{field}', got {list(decision_fields)}"
        )
