"""Spec 010 — contract tests for new CLI flags on `collect transcripts`."""

from __future__ import annotations

import re

import pytest
from typer.testing import CliRunner

from tube_scout.cli.main import app

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


class TestNewFlagsExposed:
    """FR-010-01 / FR-010-02: --prefer-captions-api and --force-refresh appear in help."""

    def test_prefer_captions_api_in_help(self, runner: CliRunner) -> None:
        result = runner.invoke(app, ["collect", "transcripts", "--help"])
        assert result.exit_code == 0
        clean = _strip_ansi(result.output)
        assert "--prefer-captions-api" in clean

    def test_force_refresh_in_help(self, runner: CliRunner) -> None:
        result = runner.invoke(app, ["collect", "transcripts", "--help"])
        assert result.exit_code == 0
        clean = _strip_ansi(result.output)
        assert "--force-refresh" in clean


class TestFlagAcceptedWithoutUsageError:
    """The flags are accepted by typer; we don't run the full pipeline here."""

    def test_prefer_captions_api_alone_accepted_at_parse(
        self, runner: CliRunner
    ) -> None:
        # Pass invalid project so the command exits cleanly post-parse,
        # but parsing the flag itself must not raise UsageError.
        result = runner.invoke(
            app,
            [
                "collect",
                "transcripts",
                "--prefer-captions-api",
                "--data-dir",
                "/nonexistent/path",
            ],
        )
        # Either the command runs and fails for a non-flag reason, or it exits
        # cleanly. The KEY assertion is that the flag itself is accepted at
        # parse-time (no "Got unexpected extra argument" / typer UsageError).
        clean = _strip_ansi(result.output)
        assert "Got unexpected extra argument" not in clean
        assert "No such option" not in clean

    def test_force_refresh_alone_accepted_at_parse(self, runner: CliRunner) -> None:
        result = runner.invoke(
            app,
            [
                "collect",
                "transcripts",
                "--force-refresh",
                "--data-dir",
                "/nonexistent/path",
            ],
        )
        clean = _strip_ansi(result.output)
        assert "Got unexpected extra argument" not in clean
        assert "No such option" not in clean

    def test_both_flags_compose(self, runner: CliRunner) -> None:
        result = runner.invoke(
            app,
            [
                "collect",
                "transcripts",
                "--prefer-captions-api",
                "--force-refresh",
                "--data-dir",
                "/nonexistent/path",
            ],
        )
        clean = _strip_ansi(result.output)
        assert "Got unexpected extra argument" not in clean
        assert "No such option" not in clean
