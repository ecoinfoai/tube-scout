"""Contract tests for spec 011 service-layer signatures (T020 RED).

Verifies that nc2_matcher and pair_checkpoint expose the exact function
signatures defined in contracts/service_layer.md §1 and §6, and that
all functions carry a non-trivial Google docstring.
"""

import inspect


def _assert_sig(func, param_names: list[str], min_doc_len: int = 10) -> None:
    sig = inspect.signature(func)
    assert list(sig.parameters.keys()) == param_names, (
        f"{func.__qualname__}: expected params {param_names}, "
        f"got {list(sig.parameters.keys())}"
    )
    doc = inspect.getdoc(func)
    assert doc is not None and len(doc) >= min_doc_len, (
        f"{func.__qualname__}: missing or too-short docstring (len={len(doc or '')})"
    )


def test_nc2_signatures() -> None:
    """nc2_matcher functions match service_layer.md §1 + spec 013 §A signatures."""
    from tube_scout.services.nc2_matcher import generate_nc2_pairs, get_caption_pool

    _assert_sig(get_caption_pool, ["professor_id", "db_path"])
    # spec 013 extended generate_nc2_pairs with optional layer_a_min_seconds
    _assert_sig(
        generate_nc2_pairs,
        ["professor_id", "db_path", "captions_dir", "cosine_cull_threshold", "layer_a_min_seconds"],
    )


def test_pair_checkpoint_signatures() -> None:
    """pair_checkpoint functions match service_layer.md §6 signatures."""
    from tube_scout.services.pair_checkpoint import (
        finalize_run,
        iterate_unfinished_pairs,
        mark_pair_done,
        resume_run,
        start_run,
    )

    _assert_sig(start_run, ["professor_id", "matching_mode", "pair_count_total", "db_path"])
    _assert_sig(iterate_unfinished_pairs, ["pool", "matching_mode", "db_path"])
    _assert_sig(mark_pair_done, ["run_id", "db_path"])
    _assert_sig(finalize_run, ["run_id", "db_path", "status"])
    _assert_sig(resume_run, ["professor_id", "matching_mode", "db_path"])


def test_professor_resolver_signatures() -> None:
    """professor_resolver functions match service_layer.md §7 signatures."""
    from tube_scout.services.professor_resolver import (
        map_professor,
        resolve_caption_pool,
    )

    sig = inspect.signature(resolve_caption_pool)
    assert "professor_id" in sig.parameters
    assert "db_path" in sig.parameters

    sig = inspect.signature(map_professor)
    assert "professor_id" in sig.parameters
    assert "channel_alias" in sig.parameters


def test_baseline_corpus_signatures() -> None:
    """baseline_corpus functions match service_layer.md §4 signatures (T045)."""
    from tube_scout.services.baseline_corpus import (
        add_baseline_phrase,
        bootstrap_baseline,
        list_baseline,
        remove_baseline_phrase,
        subtract_baseline,
    )

    _assert_sig(
        bootstrap_baseline,
        ["professor_id", "db_path", "captions_dir", "earliest_n", "min_occurrences", "registered_by"],
    )
    _assert_sig(
        add_baseline_phrase,
        ["professor_id", "phrase_raw", "db_path", "source_video_ids", "registered_by"],
    )
    _assert_sig(list_baseline, ["professor_id", "db_path"])
    _assert_sig(remove_baseline_phrase, ["professor_id", "phrase_raw", "db_path"])
    _assert_sig(subtract_baseline, ["professor_id", "spans", "db_path"])


def test_pattern_classifier_signature() -> None:
    """pattern_classifier.classify_reuse_pattern matches service_layer.md §8 (T045)."""
    from tube_scout.services.pattern_classifier import classify_reuse_pattern

    _assert_sig(
        classify_reuse_pattern,
        ["comparison", "durations", "same_week", "policy"],
    )


def test_layer_defense_signature() -> None:
    """layer_defense.apply_layers matches service_layer.md §3 (T046)."""
    from tube_scout.services.layer_defense import apply_layers

    _assert_sig(
        apply_layers,
        ["comparison", "spans", "professor_id", "db_path", "policy"],
    )
