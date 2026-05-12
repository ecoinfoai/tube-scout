"""Unit tests for NonTTYProgressReporter throttle + format (spec 013 T020 RED).

Module does not exist yet — all tests fail at import.
"""

import re


def test_nontty_throttle_emits_every_n_items(capsys) -> None:
    """With throttle_n=5, only every 5th item (and the final) emits a log line."""
    from tube_scout.services.progress_reporter import NonTTYProgressReporter

    total = 10
    reporter = NonTTYProgressReporter(
        "normalize", total=total, throttle_n=5, throttle_seconds=9999.0
    )
    with reporter:
        for i in range(1, total + 1):
            reporter.update(f"vid{i:011d}", i)

    captured = capsys.readouterr()
    # __enter__ emits "starting", __exit__ emits "finished"
    # update emits at n=5 (throttle_n boundary) and n=10 (final == total)
    update_lines = [
        ln for ln in captured.out.splitlines()
        if "video_id=" in ln
    ]
    assert len(update_lines) == 2, (
        f"Expected 2 update lines (n=5, n=10), got {len(update_lines)}: {update_lines}"
    )
    assert "N=5/" in update_lines[0]
    assert "N=10/" in update_lines[1]


def test_nontty_throttle_emits_every_k_seconds(capsys, monkeypatch) -> None:
    """With throttle_seconds=0.0, every update emits (time threshold always exceeded)."""
    from tube_scout.services.progress_reporter import NonTTYProgressReporter

    total = 4
    reporter = NonTTYProgressReporter(
        "transcripts", total=total, throttle_n=9999, throttle_seconds=0.0
    )
    with reporter:
        for i in range(1, total + 1):
            reporter.update(f"vid{i:011d}", i)

    captured = capsys.readouterr()
    update_lines = [ln for ln in captured.out.splitlines() if "video_id=" in ln]
    # throttle_seconds=0 means time threshold always fires — all 4 items emit
    assert len(update_lines) == total, (
        f"Expected {total} update lines, got {len(update_lines)}: {update_lines}"
    )


def test_nontty_eta_not_shown_in_first_3_items(capsys) -> None:
    """First 3 updates show ETA=? (insufficient sample); n>=3 with elapsed may show numeric."""
    from tube_scout.services.progress_reporter import NonTTYProgressReporter

    total = 5
    reporter = NonTTYProgressReporter(
        "analyze", total=total, throttle_n=1, throttle_seconds=0.0
    )
    with reporter:
        for i in range(1, 4):  # n=1,2,3
            reporter.update(f"vid{i:011d}", i)

    captured = capsys.readouterr()
    update_lines = [ln for ln in captured.out.splitlines() if "video_id=" in ln]
    for ln in update_lines:
        assert "ETA=?" in ln, f"Expected ETA=? in first 3 items, got: {ln!r}"


def test_nontty_force_emit_on_final_item(capsys) -> None:
    """n == total always emits regardless of throttle_n."""
    from tube_scout.services.progress_reporter import NonTTYProgressReporter

    total = 20
    reporter = NonTTYProgressReporter(
        "fingerprint", total=total, throttle_n=9999, throttle_seconds=9999.0
    )
    with reporter:
        for i in range(1, total + 1):
            reporter.update(f"vid{i:011d}", i)

    captured = capsys.readouterr()
    update_lines = [ln for ln in captured.out.splitlines() if "video_id=" in ln]
    assert len(update_lines) >= 1, "Expected at least the final item to emit"
    assert f"N={total}/" in update_lines[-1], (
        f"Final emitted line should have N={total}, got: {update_lines[-1]!r}"
    )


def test_nontty_log_line_format_regex(capsys) -> None:
    """Update lines match the structured log format defined in the contract."""
    from tube_scout.services.progress_reporter import NonTTYProgressReporter

    pattern = re.compile(
        r"^\[\w+\] video_id=\S+ N=\d+/total=\d+ elapsed=[\d.]+s ETA=(\d+s|\?)$"
    )
    total = 5
    reporter = NonTTYProgressReporter(
        "kb_export", total=total, throttle_n=1, throttle_seconds=0.0
    )
    with reporter:
        for i in range(1, total + 1):
            reporter.update(f"vid{i:011d}", i)

    captured = capsys.readouterr()
    update_lines = [ln for ln in captured.out.splitlines() if "video_id=" in ln]
    assert update_lines, "No update lines emitted"
    for ln in update_lines:
        assert pattern.match(ln), f"Line does not match format: {ln!r}"
