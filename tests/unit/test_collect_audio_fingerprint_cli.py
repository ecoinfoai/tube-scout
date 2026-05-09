"""T030 RED — collect audio + collect fingerprint CLI 5 scenarios."""
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from tube_scout.cli.main import app

runner = CliRunner()


def test_collect_audio_channel_dispatches(tmp_path) -> None:
    """Scenario 1: collect audio --channel <alias> dispatches to audio pipeline."""
    captured: dict = {}

    def fake_dispatch(**kwargs):
        captured.update(kwargs)

    with patch(
        "tube_scout.cli.collect.dispatch_audio_fingerprint",
        side_effect=fake_dispatch,
    ), patch(
        "tube_scout.cli.collect.resolve_alias_to_channel_id",
        return_value="UC_TEST_001",
    ):
        result = runner.invoke(
            app,
            ["collect", "audio", "--channel", "nursing"],
        )

    assert captured.get("channel") == "nursing"


def test_collect_fingerprint_alias_equals_collect_audio(tmp_path) -> None:
    """Scenario 2: collect fingerprint --channel X behaves same as collect audio --channel X."""
    audio_captured: dict = {}
    fingerprint_captured: dict = {}

    def fake_audio_dispatch(**kwargs):
        audio_captured.update(kwargs)

    def fake_fingerprint_dispatch(**kwargs):
        fingerprint_captured.update(kwargs)

    with patch(
        "tube_scout.cli.collect.dispatch_audio_fingerprint",
        side_effect=fake_audio_dispatch,
    ), patch(
        "tube_scout.cli.collect.resolve_alias_to_channel_id",
        return_value="UC_TEST_002",
    ):
        runner.invoke(app, ["collect", "audio", "--channel", "nursing"])

    with patch(
        "tube_scout.cli.collect.dispatch_audio_fingerprint",
        side_effect=fake_fingerprint_dispatch,
    ), patch(
        "tube_scout.cli.collect.resolve_alias_to_channel_id",
        return_value="UC_TEST_002",
    ):
        runner.invoke(app, ["collect", "fingerprint", "--channel", "nursing"])

    assert audio_captured.get("channel") == fingerprint_captured.get("channel")


def test_collect_audio_all_channels(tmp_path) -> None:
    """Scenario 3: collect audio --all-channels dispatches with all_channels=True."""
    captured: dict = {}

    def fake_dispatch(**kwargs):
        captured.update(kwargs)

    with patch(
        "tube_scout.cli.collect.dispatch_audio_fingerprint",
        side_effect=fake_dispatch,
    ):
        result = runner.invoke(
            app,
            ["collect", "audio", "--all-channels"],
        )

    assert captured.get("all_channels") is True


def test_collect_audio_force_flag(tmp_path) -> None:
    """Scenario 4: collect audio --force sets force=True in dispatch."""
    captured: dict = {}

    def fake_dispatch(**kwargs):
        captured.update(kwargs)

    with patch(
        "tube_scout.cli.collect.dispatch_audio_fingerprint",
        side_effect=fake_dispatch,
    ), patch(
        "tube_scout.cli.collect.resolve_alias_to_channel_id",
        return_value="UC_TEST_004",
    ):
        result = runner.invoke(
            app,
            ["collect", "audio", "--channel", "nursing", "--force"],
        )

    assert captured.get("force") is True


def test_collect_audio_channel_and_all_channels_mutual_exclusion() -> None:
    """Scenario 5: collect audio --channel X --all-channels → exit 2."""
    result = runner.invoke(
        app,
        ["collect", "audio", "--channel", "nursing", "--all-channels"],
    )
    assert result.exit_code == 2
