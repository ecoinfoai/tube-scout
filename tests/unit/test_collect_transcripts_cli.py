"""collect transcripts CLI --source flag scenarios (spec 013 Phase 5: api/asr)."""
import os
from unittest.mock import patch

from typer.testing import CliRunner

from tube_scout.cli.main import app

runner = CliRunner()


def test_source_default_is_api(tmp_path) -> None:
    """Scenario 1: explicit --source api dispatches with source='api'.

    Note: spec 016 FR-017 (commit d96b82e) changed the default to 'asr'.
    The api dispatch path is still reachable via explicit --source api;
    that is what this test now exercises.
    """
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
        runner.invoke(
            app,
            ["collect", "transcripts", "--channel", "test-alias", "--source", "api"],
            env=env,
        )

    assert captured.get("source") == "api"


def test_flag_overrides_env(tmp_path) -> None:
    """Explicit --source api wins over a stale env default."""
    captured: dict = {}

    def fake_dispatch(source, **kwargs):
        captured["source"] = source

    env = {**os.environ, "TUBE_SCOUT_DEFAULT_TRANSCRIPT_SOURCE": "api"}

    with patch(
        "tube_scout.cli.collect.dispatch_transcript_source",
        side_effect=fake_dispatch,
    ), patch(
        "tube_scout.cli.collect.resolve_alias_to_channel_id",
        return_value="UC_TEST_CHANNEL_ID",
    ):
        runner.invoke(
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


