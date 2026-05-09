"""T016 RED — pick_priority_track 4 scenarios."""
from pathlib import Path

import pytest


def test_both_manual_and_auto_returns_manual() -> None:
    """Scenario 1: both paths present → manual wins."""
    from tube_scout.services.srv3_parser import pick_priority_track

    manual = Path("video.ko.srv3")
    auto = Path("video.ko-orig.srv3")
    result = pick_priority_track(manual, auto)
    assert result == (manual, "ytdlp:manual")


def test_only_auto_returns_auto() -> None:
    """Scenario 2: manual=None, auto present → auto returned."""
    from tube_scout.services.srv3_parser import pick_priority_track

    auto = Path("video.ko.srv3")
    result = pick_priority_track(None, auto)
    assert result == (auto, "ytdlp:auto")


def test_only_manual_returns_manual() -> None:
    """Scenario 3: auto=None, manual present → manual returned."""
    from tube_scout.services.srv3_parser import pick_priority_track

    manual = Path("video.ko.srv3")
    result = pick_priority_track(manual, None)
    assert result == (manual, "ytdlp:manual")


def test_both_none_returns_none() -> None:
    """Scenario 4: both None → None (no_captions_available signal)."""
    from tube_scout.services.srv3_parser import pick_priority_track

    result = pick_priority_track(None, None)
    assert result is None
