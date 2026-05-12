"""Contract tests for progress_reporter factory + Protocol (spec 013 T019 RED).

FR-061: make_progress_reporter auto-detects TTY and returns the correct impl.
Module does not exist yet — all tests should fail at import.
"""


def test_make_progress_reporter_returns_tty_when_stdout_is_tty() -> None:
    """make_progress_reporter with force_tty=True returns a TTY impl."""
    from tube_scout.services.progress_reporter import (
        TTYProgressReporter,
        make_progress_reporter,
    )

    reporter = make_progress_reporter("audio_extract", total=5, force_tty=True)
    assert isinstance(reporter, TTYProgressReporter)


def test_make_progress_reporter_returns_nontty_when_stdout_is_not_tty() -> None:
    """make_progress_reporter with force_tty=False returns a NonTTY impl."""
    from tube_scout.services.progress_reporter import (
        NonTTYProgressReporter,
        make_progress_reporter,
    )

    reporter = make_progress_reporter("audio_extract", total=5, force_tty=False)
    assert isinstance(reporter, NonTTYProgressReporter)


def test_progress_reporter_signature_matches_protocol() -> None:
    """Returned object exposes __enter__, __exit__, and update(video_id, n)."""
    from tube_scout.services.progress_reporter import make_progress_reporter

    reporter = make_progress_reporter("normalize", total=3, force_tty=False)

    assert hasattr(reporter, "__enter__"), "missing __enter__"
    assert hasattr(reporter, "__exit__"), "missing __exit__"
    assert callable(getattr(reporter, "update", None)), "missing callable update"

    import inspect

    sig = inspect.signature(reporter.update)
    params = list(sig.parameters)
    assert "video_id" in params, f"update() missing video_id param, got {params}"
    assert "n" in params, f"update() missing n param, got {params}"
