"""Contract tests for FR-006/FR-007 — symmetric --channel API across collect commands.

Every `tube-scout collect <subcommand>` MUST accept `--channel <alias>`.
Help text MUST mention it. Invalid alias MUST raise UserFacingError with
non-empty next_command.

Spec 009 Phase 5 (US3) — T029.
"""

from __future__ import annotations

import re

import pytest
from typer.testing import CliRunner

from tube_scout.cli.main import app

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _strip_ansi(text: str) -> str:
    """Remove ANSI escape sequences so token matches survive rich coloring.

    CI runners set FORCE_COLOR, which makes typer/rich split the literal
    "--channel" into separate ANSI-wrapped dashes ("--" → "\\x1b[36m-\\x1b[0m\\x1b[36m-channel\\x1b[0m").
    A plain substring match on result.output then fails even though the
    option is rendered. Stripping ANSI codes before the assertion keeps
    the test environment-agnostic.
    """
    return _ANSI_RE.sub("", text)


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


SUBCOMMANDS = (
    "videos",
    "transcripts",
    "comments",
    "retention",
    "analytics",
    "bulk",
    "all",
)


@pytest.mark.parametrize("subcmd", SUBCOMMANDS)
def test_subcommand_help_mentions_channel_option(
    runner: CliRunner, subcmd: str
) -> None:
    """Every collect subcommand's --help text MUST mention --channel."""
    result = runner.invoke(app, ["collect", subcmd, "--help"])
    assert result.exit_code == 0, f"--help failed for collect {subcmd}: {result.output}"
    assert "--channel" in _strip_ansi(result.output), (
        f"collect {subcmd} --help does not mention --channel option"
    )


@pytest.mark.parametrize(
    "subcmd",
    ["videos", "transcripts", "comments", "retention", "analytics"],
)
def test_subcommand_rejects_invalid_alias_format(
    runner: CliRunner, subcmd: str, tmp_path
) -> None:
    """Invalid alias (path traversal) MUST be rejected with non-zero exit."""
    args = [
        "collect",
        subcmd,
        "--channel",
        "../evil",
        "--project-dir",
        str(tmp_path / "projects"),
        "--data-dir",
        str(tmp_path / "data"),
    ]
    if subcmd == "bulk":
        args.extend(["--report-type", "channel_basic_a2"])
    result = runner.invoke(app, args)
    assert result.exit_code != 0, f"collect {subcmd} accepted invalid alias '../evil'"
