"""T039 RED: FR-019 + SC-008 — unregistered channel must exit 5 with 0 yt-dlp calls.

Phase 5 / User Story 3: alias resolver gate prevents any yt-dlp/network call for
unregistered aliases and direct video URLs.
"""

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from tube_scout.cli.main import app


@pytest.fixture()
def runner() -> CliRunner:
    return CliRunner()


# ---------------------------------------------------------------------------
# Scenario 1: unregistered alias → exit 5, subprocess.run never called
# ---------------------------------------------------------------------------

def test_unregistered_alias_exits_5_no_ytdlp_call(runner: CliRunner, tmp_path: Path) -> None:
    """FR-019: unregistered --channel alias must exit 5; yt-dlp subprocess.run call count == 0."""
    spy_calls: list = []

    def _fake_run(cmd: list, **kwargs: object) -> subprocess.CompletedProcess:
        spy_calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    with patch("tube_scout.services.auth.load_registry") as mock_registry, \
         patch("tube_scout.cli.collect.resolve_alias_to_channel_id") as mock_resolve, \
         patch("subprocess.run", side_effect=_fake_run):

        mock_registry.return_value = {}
        mock_resolve.side_effect = KeyError("not-a-real-channel")

        result = runner.invoke(
            app,
            ["collect", "transcripts", "--channel", "not-a-real-channel", "--source", "ytdlp"],
        )

    assert result.exit_code == 5, (
        f"Expected exit 5 for unregistered alias, got {result.exit_code}. "
        f"Output: {result.output}"
    )
    ytdlp_calls = [c for c in spy_calls if any("yt-dlp" in str(arg) for arg in c)]
    assert len(ytdlp_calls) == 0, (
        f"SC-008 violated: yt-dlp was called {len(ytdlp_calls)} time(s) for unregistered alias"
    )


# ---------------------------------------------------------------------------
# Scenario 2: direct video URL bypasses alias → must still exit 5
# ---------------------------------------------------------------------------

def test_direct_video_url_bypass_rejected(runner: CliRunner, tmp_path: Path) -> None:
    """SC-008: passing a raw YouTube URL instead of alias must exit 5 with 0 yt-dlp calls."""
    spy_calls: list = []

    def _fake_run(cmd: list, **kwargs: object) -> subprocess.CompletedProcess:
        spy_calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    raw_url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

    with patch("tube_scout.cli.collect.resolve_alias_to_channel_id") as mock_resolve, \
         patch("subprocess.run", side_effect=_fake_run):

        # resolve_alias_to_channel_id must raise for a raw URL
        mock_resolve.side_effect = KeyError("raw URL is not a registered alias")

        result = runner.invoke(
            app,
            ["collect", "audio", "--channel", raw_url],
        )

    assert result.exit_code == 5, (
        f"Expected exit 5 for raw URL channel arg, got {result.exit_code}. "
        f"Output: {result.output}"
    )
    ytdlp_calls = [c for c in spy_calls if any("yt-dlp" in str(arg) for arg in c)]
    assert len(ytdlp_calls) == 0, (
        f"SC-008 violated: yt-dlp was called for raw URL bypass attempt"
    )


# ---------------------------------------------------------------------------
# Scenario 3: --all-channels with empty registry → exit 5, 0 yt-dlp calls
# ---------------------------------------------------------------------------

def test_all_channels_empty_registry_exits_5(runner: CliRunner, tmp_path: Path) -> None:
    """FR-019: --all-channels with no registered channels must exit 5 with 0 yt-dlp calls."""
    spy_calls: list = []

    def _fake_run(cmd: list, **kwargs: object) -> subprocess.CompletedProcess:
        spy_calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    with patch("tube_scout.services.auth.load_registry") as mock_registry, \
         patch("subprocess.run", side_effect=_fake_run):

        mock_registry.return_value = {}  # empty registry

        result = runner.invoke(
            app,
            ["collect", "fingerprint", "--all-channels"],
        )

    # With empty registry, --all-channels should exit 5 (no channels to process)
    assert result.exit_code == 5, (
        f"Expected exit 5 for --all-channels with empty registry, got {result.exit_code}. "
        f"Output: {result.output}"
    )
    ytdlp_calls = [c for c in spy_calls if any("yt-dlp" in str(arg) for arg in c)]
    assert len(ytdlp_calls) == 0, (
        f"SC-008 violated: yt-dlp was called with empty registry"
    )
