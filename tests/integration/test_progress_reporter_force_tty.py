"""Integration tests for make_progress_reporter force_tty=True/False (spec 013 T021 RED).

Instantiate with force_tty=True and force_tty=False, call update() 100 times,
verify no exceptions and mode-specific output behavior.
Module does not exist yet — all tests fail at import.
"""


def test_force_tty_true_runs_100_updates_no_exception(capsys) -> None:
    """TTY mode: 100 update() calls complete without exception."""
    from tube_scout.services.progress_reporter import make_progress_reporter

    total = 100
    with make_progress_reporter("audio_extract", total=total, force_tty=True) as r:
        for i in range(1, total + 1):
            r.update(f"vid{i:011d}", i)


def test_force_tty_false_runs_100_updates_no_exception(capsys) -> None:
    """NonTTY mode: 100 update() calls complete without exception."""
    from tube_scout.services.progress_reporter import make_progress_reporter

    total = 100
    with make_progress_reporter(
        "audio_extract", total=total, force_tty=False, nontty_throttle_n=10
    ) as r:
        for i in range(1, total + 1):
            r.update(f"vid{i:011d}", i)


def test_force_tty_true_does_not_emit_plain_stdout_per_update(capsys) -> None:
    """TTY mode (rich.progress) must not emit a plain text line per update call."""
    from tube_scout.services.progress_reporter import make_progress_reporter

    total = 10
    with make_progress_reporter("normalize", total=total, force_tty=True) as r:
        for i in range(1, total + 1):
            r.update(f"vid{i:011d}", i)

    captured = capsys.readouterr()
    # rich writes to its own console/stderr; plain stdout should have no "N=x/total=" lines
    update_lines = [ln for ln in captured.out.splitlines() if "N=" in ln and "total=" in ln]
    assert len(update_lines) == 0, (
        f"TTY mode must not emit plain stdout update lines, got: {update_lines}"
    )


def test_force_tty_false_emits_throttled_lines(capsys) -> None:
    """NonTTY mode with throttle_n=25 emits throttled progress lines to stdout."""
    from tube_scout.services.progress_reporter import make_progress_reporter

    total = 100
    with make_progress_reporter(
        "transcripts",
        total=total,
        force_tty=False,
        nontty_throttle_n=25,
        nontty_throttle_seconds=9999.0,
    ) as r:
        for i in range(1, total + 1):
            r.update(f"vid{i:011d}", i)

    captured = capsys.readouterr()
    update_lines = [ln for ln in captured.out.splitlines() if "N=" in ln and "total=" in ln]
    # throttle_n=25 → emits at n=25, n=50, n=75, n=100 (final) = 4 lines
    assert len(update_lines) >= 1, "NonTTY mode must emit at least one throttled line"
    # final item always emits
    assert any("N=100/total=100" in ln for ln in update_lines), (
        "Final item (N=100) must always emit in NonTTY mode"
    )
