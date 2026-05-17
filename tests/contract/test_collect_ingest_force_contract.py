"""T035 RED — contract tests for collect ingest --force CLI option.

Contract: collect-ingest-force.md §1~§4.
(a) tube-scout collect ingest --help output contains --force
(b) --force has Typer type bool, default False
(c) Without --force, existing behavior unchanged (idempotency guard active)
"""

from __future__ import annotations

import inspect

from typer.testing import CliRunner


class TestForceOptionInHelp:
    """§4: --help output must include --force."""

    def test_collect_ingest_help_contains_force_flag(self) -> None:
        """tube-scout collect ingest --help shows --force option."""
        from tube_scout.cli.main import app

        runner = CliRunner()
        result = runner.invoke(app, ["collect", "ingest", "--help"])

        assert result.exit_code == 0, f"help failed: {result.output}"
        assert "--force" in result.output, (
            f"--force not found in collect ingest --help output:\n{result.output}"
        )

    def test_collect_ingest_help_force_mentions_idempotency(self) -> None:
        """--help text for --force mentions idempotency guard bypass."""
        from tube_scout.cli.main import app

        runner = CliRunner()
        result = runner.invoke(app, ["collect", "ingest", "--help"])

        assert result.exit_code == 0
        # Help text should contain key phrase about guard bypass
        output_lower = result.output.lower()
        assert any(
            phrase in output_lower
            for phrase in ["강제", "force", "멱등", "우회", "재처리"]
        ), (
            f"--force help text does not describe idempotency bypass:\n{result.output}"
        )


class TestForceOptionSignature:
    """§1: collect_ingest_command signature has force: bool = False."""

    def test_force_param_exists_with_bool_type(self) -> None:
        """collect_ingest_command has force parameter typed as bool."""
        from tube_scout.cli.collect import collect_ingest_command

        sig = inspect.signature(collect_ingest_command)
        assert "force" in sig.parameters, (
            "collect_ingest_command missing 'force' parameter"
        )
        param = sig.parameters["force"]
        # Typer wraps the default in OptionInfo — check annotation
        assert param.annotation in (bool, inspect.Parameter.empty) or (
            hasattr(param.default, "default") and isinstance(param.default.default, bool)
        ), f"force parameter annotation/default not bool: {param}"

    def test_force_param_default_is_false(self) -> None:
        """force parameter default value is False."""
        from tube_scout.cli.collect import collect_ingest_command

        sig = inspect.signature(collect_ingest_command)
        param = sig.parameters["force"]
        # Typer OptionInfo stores the actual default in .default attribute
        if hasattr(param.default, "default"):
            assert param.default.default is False, (
                f"force default should be False, got {param.default.default}"
            )
        else:
            assert param.default is False, (
                f"force default should be False, got {param.default}"
            )


class TestIngestUnifiedForceSignature:
    """ingest_unified must accept force kwarg for CLI plumbing."""

    def test_ingest_unified_has_force_param(self) -> None:
        """ingest_unified signature includes force: bool = False."""
        from tube_scout.services.unified_ingest import ingest_unified

        sig = inspect.signature(ingest_unified)
        assert "force" in sig.parameters, (
            "ingest_unified missing 'force' parameter — needed for CLI plumbing"
        )

    def test_ingest_unified_force_default_false(self) -> None:
        """ingest_unified force default is False."""
        from tube_scout.services.unified_ingest import ingest_unified

        sig = inspect.signature(ingest_unified)
        param = sig.parameters["force"]
        assert param.default is False, (
            f"ingest_unified force default should be False, got {param.default}"
        )
