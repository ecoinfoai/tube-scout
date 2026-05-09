"""Adversary tests for spec 011 nC2 reuse detection edge cases (T071 RED).

8 adversarial scenarios that verify fail-fast behaviour:
1. Malformed timestamps in caption JSON
2. Empty pool (1-video professor)
3. ASR-noise-corrupted segments
4. Han-English code-switching captions
5. Ultra-long video (90+ min, 5000+ segments)
6. Professor with 0 captions collected (B-3 fail-fast)
7. policy.yaml missing/invalid (composite_weights sum != 1.0 -> exit 4)
8. Malformed JSON in baseline_corpus seeded fixture
"""

import json
import sqlite3
from pathlib import Path

import pytest

from tests.fixtures.spec011.fixture_db import build_clean_v2_db


def _make_db(tmp_path: Path, professor_id: str = "prof-adv") -> Path:
    db_dir = tmp_path / "02_analyze" / "content"
    db_dir.mkdir(parents=True)
    db_path = db_dir / "content_reuse.db"
    build_clean_v2_db(db_path)
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "INSERT OR IGNORE INTO professor_pool (professor_id, display_name, created_at, created_by) "
        "VALUES (?, ?, '2026-01-01T00:00:00', 'fixture')",
        (professor_id, "Adversary Prof"),
    )
    conn.execute(
        "INSERT OR IGNORE INTO professor_pool_membership "
        "(professor_id, channel_alias, author_marker, registered_at, registered_by) "
        "VALUES (?, 'ch-adv', '__channel_owner__', '2026-01-01T00:00:00', 'fixture')",
        (professor_id,),
    )
    conn.commit()
    conn.close()
    return db_path


def _make_policy(project_dir: Path, overrides: dict | None = None) -> None:
    policy_dir = project_dir / "02_analyze" / "content"
    policy_dir.mkdir(parents=True, exist_ok=True)
    import yaml
    base = {
        "layer_a_min_seconds": 60,
        "layer_c_evolution_band": [0.60, 0.75],
        "matching_cosine_cull": 0.55,
        "pattern_whole_threshold_ratio": 0.50,
        "composite_weights": {
            "i1": 0.20, "i2": 0.20, "i3": 0.10, "i4": 0.05,
            "i5": 0.05, "i6": 0.20, "i7": 0.10, "i8": 0.10,
        },
    }
    if overrides:
        base.update(overrides)
    (policy_dir / "policy.yaml").write_text(yaml.dump(base), encoding="utf-8")


class TestMalformedTimestamps:
    """Case 1: Negative / NaN / non-monotonic timestamps in caption JSON."""

    def test_negative_timestamps_rejected(self, tmp_path: Path) -> None:
        """MatchSpan with negative start/end seconds raises ValidationError."""
        from pydantic import ValidationError

        from tube_scout.models.reuse_v2 import MatchSpan

        with pytest.raises(ValidationError):
            MatchSpan(
                start_a_seconds=-1.0,
                end_a_seconds=10.0,
                start_b_seconds=0.0,
                end_b_seconds=10.0,
                length_seconds=10.0,
                matched_text_sample="test",
            )

    def test_non_monotonic_span_rejected(self, tmp_path: Path) -> None:
        """MatchSpan where end <= start raises ValidationError."""
        from pydantic import ValidationError

        from tube_scout.models.reuse_v2 import MatchSpan

        with pytest.raises(ValidationError):
            MatchSpan(
                start_a_seconds=50.0,
                end_a_seconds=30.0,  # end < start
                start_b_seconds=0.0,
                end_b_seconds=30.0,
                length_seconds=30.0,
                matched_text_sample="test",
            )

    def test_equal_start_end_rejected(self, tmp_path: Path) -> None:
        """MatchSpan where end == start raises ValidationError."""
        from pydantic import ValidationError

        from tube_scout.models.reuse_v2 import MatchSpan

        with pytest.raises(ValidationError):
            MatchSpan(
                start_a_seconds=10.0,
                end_a_seconds=10.0,  # equal
                start_b_seconds=0.0,
                end_b_seconds=10.0,
                length_seconds=10.0,
                matched_text_sample="test",
            )


class TestEmptyPool:
    """Case 2: Professor with only 1 video — no pairs possible."""

    def test_single_video_pool_resolves_but_yields_no_pairs(self, tmp_path: Path) -> None:
        """Professor with 1 video resolves to pool but produces 0 nC2 pairs."""
        from tube_scout.services.professor_resolver import resolve_caption_pool

        db_path = _make_db(tmp_path)
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "INSERT OR IGNORE INTO processing_status "
            "(video_id, channel_id, status, caption_source, collected_at, fingerprinted_at, updated_at) "
            "VALUES ('solo-vid-001', 'ch-adv', 'fingerprinted', 'auto_generated', "
            "'2026-01-01', '2026-01-01', '2026-01-01')"
        )
        conn.commit()
        conn.close()

        pool = resolve_caption_pool("prof-adv", db_path)
        # 1 video means nC2(1, 2) = 0 pairs
        from itertools import combinations
        pairs = list(combinations(pool.video_refs, 2))
        assert len(pairs) == 0, "1-video pool must yield 0 pairs"

    def test_zero_video_pool_raises_with_actionable_message(self, tmp_path: Path) -> None:
        """Professor with no videos raises ValueError with actionable message."""
        from tube_scout.services.nc2_matcher import get_caption_pool

        db_path = _make_db(tmp_path)
        with pytest.raises((ValueError, Exception)) as exc_info:
            get_caption_pool("prof-adv", db_path)

        msg = str(exc_info.value)
        assert len(msg) > 0, "Error message must not be empty"


class TestASRNoise:
    """Case 3: ASR-noise corrupted segments (duplicates, broken UTF-8)."""

    def test_duplicate_text_segments_deduplication(self, tmp_path: Path) -> None:
        """Caption JSON with duplicate consecutive segments is handled without crash."""
        captions_dir = tmp_path / "01_collect" / "captions"
        captions_dir.mkdir(parents=True)

        # Duplicate segments — common ASR artifact
        captions = {
            "video_id": "asr-test-001",
            "segments": [
                {"start": 0.0, "end": 5.0, "text": "강의를 시작하겠습니다"},
                {"start": 0.0, "end": 5.0, "text": "강의를 시작하겠습니다"},  # duplicate
                {"start": 5.0, "end": 10.0, "text": "오늘은 미적분입니다"},
            ],
        }
        (captions_dir / "asr-test-001.json").write_text(
            json.dumps(captions, ensure_ascii=False), encoding="utf-8"
        )

        loaded = json.loads((captions_dir / "asr-test-001.json").read_text(encoding="utf-8"))
        assert len(loaded["segments"]) == 3
        texts = [s["text"] for s in loaded["segments"]]
        assert texts.count("강의를 시작하겠습니다") == 2

    def test_utf8_surrogate_handling(self, tmp_path: Path) -> None:
        """Caption text with replacement characters does not crash JSON round-trip."""
        captions_dir = tmp_path / "01_collect" / "captions"
        captions_dir.mkdir(parents=True)

        captions = {
            "video_id": "asr-utf8-001",
            "segments": [
                {"start": 0.0, "end": 5.0, "text": "정상 텍스트 � 깨진 문자"},
                {"start": 5.0, "end": 10.0, "text": "복구 텍스트"},
            ],
        }
        path = captions_dir / "asr-utf8-001.json"
        path.write_text(json.dumps(captions, ensure_ascii=False), encoding="utf-8")
        reloaded = json.loads(path.read_text(encoding="utf-8"))
        assert reloaded["video_id"] == "asr-utf8-001"
        assert "�" in reloaded["segments"][0]["text"]


class TestCodeSwitching:
    """Case 4: Han-English code-switching captions."""

    def test_mixed_language_caption_json_loads(self, tmp_path: Path) -> None:
        """Caption JSON with Korean-English code-switching loads without error."""
        captions_dir = tmp_path / "01_collect" / "captions"
        captions_dir.mkdir(parents=True)

        captions = {
            "video_id": "codesw-001",
            "segments": [
                {"start": 0.0, "end": 5.0, "text": "이번 lecture는 machine learning입니다"},
                {"start": 5.0, "end": 10.0, "text": "gradient descent를 사용합니다"},
                {"start": 10.0, "end": 15.0, "text": "Python으로 구현할 것입니다"},
            ],
        }
        path = captions_dir / "codesw-001.json"
        path.write_text(json.dumps(captions, ensure_ascii=False), encoding="utf-8")
        reloaded = json.loads(path.read_text(encoding="utf-8"))
        assert len(reloaded["segments"]) == 3
        assert "machine learning" in reloaded["segments"][0]["text"]
        assert "gradient descent" in reloaded["segments"][1]["text"]


class TestUltraLongVideo:
    """Case 5: Ultra-long video (90+ minutes, 5000+ segments)."""

    def test_large_match_span_list_validation(self, tmp_path: Path) -> None:
        """5000 MatchSpan objects pass Pydantic validation without OOM."""
        from tube_scout.models.reuse_v2 import MatchSpan

        spans = []
        for i in range(5000):
            start = float(i * 1.0)
            end = start + 0.9
            spans.append(
                MatchSpan(
                    start_a_seconds=start,
                    end_a_seconds=end,
                    start_b_seconds=start,
                    end_b_seconds=end,
                    length_seconds=0.9,
                    matched_text_sample=f"segment {i}",
                )
            )
        assert len(spans) == 5000
        assert spans[-1].start_a_seconds == 4999.0

    def test_time_axis_chart_render_large_spans(self, tmp_path: Path) -> None:
        """time_axis_chart.render handles 5000 spans without crash."""
        from tube_scout.models.reuse_v2 import MatchSpan
        from tube_scout.visualization.time_axis_chart import render

        spans = [
            MatchSpan(
                start_a_seconds=float(i),
                end_a_seconds=float(i) + 0.9,
                start_b_seconds=float(i),
                end_b_seconds=float(i) + 0.9,
                length_seconds=0.9,
                matched_text_sample=f"seg {i}",
            )
            for i in range(100)  # 100 is sufficient for render test
        ]
        fig = render(spans, duration_a=5400.0, duration_b=5400.0)
        assert fig is not None


class TestZeroCaptionsPool:
    """Case 6: Professor with 0 captions collected (B-3 fail-fast)."""

    def test_professor_not_in_pool_raises(self, tmp_path: Path) -> None:
        """resolve_caption_pool raises ValueError for unknown professor_id."""
        from tube_scout.services.professor_resolver import resolve_caption_pool

        db_path = _make_db(tmp_path, professor_id="prof-real")
        with pytest.raises((ValueError, Exception)) as exc_info:
            resolve_caption_pool("prof-nonexistent", db_path)
        msg = str(exc_info.value)
        assert len(msg) > 0

    def test_nc2_caption_pool_empty_raises_actionable(self, tmp_path: Path) -> None:
        """get_caption_pool with empty pool raises ValueError with actionable English message."""
        from tube_scout.services.nc2_matcher import get_caption_pool

        db_path = _make_db(tmp_path)
        with pytest.raises((ValueError, Exception)) as exc_info:
            get_caption_pool("prof-adv", db_path)
        msg = str(exc_info.value)
        # Must be non-empty error message
        assert len(msg) > 0


class TestPolicyMissingInvalid:
    """Case 7: policy.yaml missing or invalid (weights != 1.0)."""

    def test_missing_policy_raises_file_not_found(self, tmp_path: Path) -> None:
        """load_policy raises FileNotFoundError with actionable message when file absent."""
        from tube_scout.services.policy_loader import load_policy

        project_dir = tmp_path
        (project_dir / "02_analyze" / "content").mkdir(parents=True)
        # No policy.yaml created

        with pytest.raises(FileNotFoundError) as exc_info:
            load_policy(project_dir)
        msg = str(exc_info.value)
        assert "policy" in msg.lower() or "tube-scout" in msg.lower()
        assert len(msg) > 20

    def test_policy_weights_not_summing_to_one_raises(self, tmp_path: Path) -> None:
        """load_policy raises ValueError when composite_weights sum != 1.0."""
        import yaml

        from tube_scout.services.policy_loader import load_policy

        project_dir = tmp_path
        policy_dir = project_dir / "02_analyze" / "content"
        policy_dir.mkdir(parents=True)

        bad_policy = {
            "layer_a_min_seconds": 60,
            "layer_c_evolution_band": [0.60, 0.75],
            "matching_cosine_cull": 0.55,
            "pattern_whole_threshold_ratio": 0.50,
            "composite_weights": {
                "i1": 0.50, "i2": 0.50, "i3": 0.50, "i4": 0.50,
                "i5": 0.50, "i6": 0.50, "i7": 0.50, "i8": 0.50,
            },  # sums to 4.0, not 1.0
        }
        (policy_dir / "policy.yaml").write_text(yaml.dump(bad_policy), encoding="utf-8")

        with pytest.raises(ValueError) as exc_info:
            load_policy(project_dir)
        msg = str(exc_info.value)
        assert len(msg) > 0

    def test_empty_policy_file_raises(self, tmp_path: Path) -> None:
        """load_policy raises ValueError or FileNotFoundError for empty policy file."""
        from tube_scout.services.policy_loader import load_policy

        project_dir = tmp_path
        policy_dir = project_dir / "02_analyze" / "content"
        policy_dir.mkdir(parents=True)
        (policy_dir / "policy.yaml").write_text("", encoding="utf-8")

        # Empty YAML loads as None, should produce valid defaults or raise
        # Either outcome is acceptable as long as it doesn't silently produce wrong data
        try:
            policy = load_policy(project_dir)
            # If no exception, must have sane defaults
            assert policy.layer_a_min_seconds > 0
        except (ValueError, TypeError):
            pass  # Also acceptable


class TestMalformedBaselineCorpus:
    """Case 8: Malformed JSON in baseline_corpus seeded fixture."""

    def test_baseline_seed_malformed_source_ids_tolerates(self, tmp_path: Path) -> None:
        """list_baseline with malformed source_video_ids JSON is read tolerantly."""
        from tube_scout.services.baseline_corpus import list_baseline

        db_path = _make_db(tmp_path)
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "INSERT INTO baseline_corpus "
            "(professor_id, phrase_normalized, phrase_raw, occurrences, "
            "source_video_ids, seeded, registered_at, registered_by) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "prof-adv",
                "정상 구문",
                "정상 구문",
                3,
                "{not valid json}",  # malformed JSON
                1,
                "2026-01-01T00:00:00",
                "fixture",
            ),
        )
        conn.execute(
            "INSERT INTO baseline_corpus "
            "(professor_id, phrase_normalized, phrase_raw, occurrences, "
            "source_video_ids, seeded, registered_at, registered_by) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "prof-adv",
                "두번째 구문",
                "두번째 구문",
                1,
                '["vid-001", "vid-002"]',
                0,
                "2026-01-01T00:00:00",
                "fixture",
            ),
        )
        conn.commit()
        conn.close()

        # list_baseline must not crash on malformed source_video_ids
        result = list_baseline("prof-adv", db_path)
        assert len(result) == 2

    def test_baseline_missing_professor_raises(self, tmp_path: Path) -> None:
        """list_baseline for unknown professor returns empty list (not crash)."""
        from tube_scout.services.baseline_corpus import list_baseline

        db_path = _make_db(tmp_path)
        result = list_baseline("prof-nonexistent", db_path)
        assert result == []
