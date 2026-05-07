"""T022 RED: unit tests for PRODUCER_COMMANDS constant and is_producer() helper (US2).

PRODUCER_COMMANDS = frozenset({"collect.videos"}) is the single source of truth
for which CLI commands are allowed to create a new project.
"""

import pytest


def test_producer_commands_is_frozenset() -> None:
    """PRODUCER_COMMANDS must be a frozenset (immutable, no accidental mutation)."""
    from tube_scout.cli.project import PRODUCER_COMMANDS

    assert isinstance(PRODUCER_COMMANDS, frozenset)


def test_collect_videos_is_producer() -> None:
    """collect.videos is the only current producer."""
    from tube_scout.cli.project import PRODUCER_COMMANDS, is_producer

    assert "collect.videos" in PRODUCER_COMMANDS
    assert is_producer("collect.videos") is True


def test_consumer_commands_are_not_producers() -> None:
    """All consumer commands must return False from is_producer()."""
    from tube_scout.cli.project import is_producer

    consumer_commands = [
        "collect.transcripts",
        "collect.retention",
        "collect.analytics",
        "collect.bulk",
        "collect.comments",
        "analyze.retention",
        "analyze.engagement",
        "report.channel",
        "report.video",
        "content.scan",
        "content.compare",
    ]
    for cmd in consumer_commands:
        assert is_producer(cmd) is False, f"Expected {cmd!r} to be a consumer"


def test_is_producer_empty_string_is_false() -> None:
    """Empty string is not a producer command."""
    from tube_scout.cli.project import is_producer

    assert is_producer("") is False


def test_is_producer_unknown_command_is_false() -> None:
    """Unknown command IDs must not be treated as producers."""
    from tube_scout.cli.project import is_producer

    assert is_producer("collect.videos.extra") is False
    assert is_producer("COLLECT.VIDEOS") is False  # case sensitive
