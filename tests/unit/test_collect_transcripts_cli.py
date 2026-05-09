"""T018 RED — collect transcripts CLI --source flag 6 scenarios."""
import os
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from tube_scout.cli.main import app

runner = CliRunner()


def test_source_default_is_api(tmp_path) -> None:
    """Scenario 1: no --source flag, no env → dispatches with source='api'."""
    env = {k: v for k, v in os.environ.items() if k != "TUBE_SCOUT_DEFAULT_TRANSCRIPT_SOURCE"}

    captured: dict = {}

    def fake_dispatch(source, **kwargs):
        captured["source"] = source

    with patch(
        "tube_scout.cli.collect.dispatch_transcript_source",
        side_effect=fake_dispatch,
    ), patch(
        "tube_scout.cli.collect.resolve_alias_to_channel_id",
        return_value="UC_TEST_CHANNEL_ID",
    ):
        result = runner.invoke(
            app,
            ["collect", "transcripts", "--channel", "test-alias"],
            env=env,
        )

    assert captured.get("source") == "api"


def test_env_sets_ytdlp_source(tmp_path) -> None:
    """Scenario 2: env TUBE_SCOUT_DEFAULT_TRANSCRIPT_SOURCE=ytdlp, no flag → source='ytdlp'."""
    captured: dict = {}

    def fake_dispatch(source, **kwargs):
        captured["source"] = source

    env = {**os.environ, "TUBE_SCOUT_DEFAULT_TRANSCRIPT_SOURCE": "ytdlp"}

    with patch(
        "tube_scout.cli.collect.dispatch_transcript_source",
        side_effect=fake_dispatch,
    ), patch(
        "tube_scout.cli.collect.resolve_alias_to_channel_id",
        return_value="UC_TEST_CHANNEL_ID",
    ):
        result = runner.invoke(
            app,
            ["collect", "transcripts", "--channel", "test-alias"],
            env=env,
        )

    assert captured.get("source") == "ytdlp"


def test_flag_overrides_env(tmp_path) -> None:
    """Scenario 3: --source api + env=ytdlp → flag wins → source='api'."""
    captured: dict = {}

    def fake_dispatch(source, **kwargs):
        captured["source"] = source

    env = {**os.environ, "TUBE_SCOUT_DEFAULT_TRANSCRIPT_SOURCE": "ytdlp"}

    with patch(
        "tube_scout.cli.collect.dispatch_transcript_source",
        side_effect=fake_dispatch,
    ), patch(
        "tube_scout.cli.collect.resolve_alias_to_channel_id",
        return_value="UC_TEST_CHANNEL_ID",
    ):
        result = runner.invoke(
            app,
            ["collect", "transcripts", "--source", "api", "--channel", "test-alias"],
            env=env,
        )

    assert captured.get("source") == "api"


def test_channel_and_all_channels_mutual_exclusion() -> None:
    """Scenario 4: --channel + --all-channels → exit 2 + actionable stderr."""
    result = runner.invoke(
        app,
        ["collect", "transcripts", "--channel", "test", "--all-channels"],
    )
    assert result.exit_code == 2


def test_unknown_channel_alias_exit_5() -> None:
    """Scenario 5: --channel <unregistered> → exit 5 + actionable message."""
    with patch(
        "tube_scout.cli.collect.resolve_alias_to_channel_id",
        side_effect=KeyError("unregistered-alias"),
    ):
        result = runner.invoke(
            app,
            ["collect", "transcripts", "--channel", "unregistered-alias"],
        )

    assert result.exit_code == 5


def test_ytdlp_source_invokes_fetch_caption(tmp_path) -> None:
    """Scenario 6: --source ytdlp dispatches to fetch_caption_via_ytdlp."""
    captured: dict = {}

    def fake_dispatch(source, **kwargs):
        captured["source"] = source

    with patch(
        "tube_scout.cli.collect.dispatch_transcript_source",
        side_effect=fake_dispatch,
    ), patch(
        "tube_scout.cli.collect.resolve_alias_to_channel_id",
        return_value="UC_TEST_CHANNEL_ID",
    ):
        result = runner.invoke(
            app,
            ["collect", "transcripts", "--source", "ytdlp", "--channel", "test-alias"],
        )

    assert captured.get("source") == "ytdlp"
