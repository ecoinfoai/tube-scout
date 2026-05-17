"""T086a — G3 coverage: FR-027 negative requirement — --force-asr must NOT exist.

spec.md FR-027: The system must NOT expose a --force-asr flag on any CLI command.
Operators select ASR via --source asr; forced re-ASR is not an operator-level concern.
"""
import subprocess
import sys


def test_collect_transcripts_help_has_no_force_asr_flag() -> None:
    """FR-027: `tube-scout collect transcripts --help` must not contain '--force-asr'."""
    result = subprocess.run(
        [sys.executable, "-m", "tube_scout", "collect", "transcripts", "--help"],
        capture_output=True,
        text=True,
    )
    # help output may go to stdout or stderr depending on typer version
    combined = result.stdout + result.stderr
    assert "--force-asr" not in combined, (
        "FR-027 violated: '--force-asr' flag found in 'collect transcripts --help' output. "
        "This flag must not exist."
    )


def test_collect_transcripts_command_has_no_force_asr_param() -> None:
    """FR-027: collect_transcripts_command must not have a 'force_asr' parameter."""
    import inspect

    from tube_scout.cli.collect import collect_transcripts_command

    params = inspect.signature(collect_transcripts_command).parameters
    assert "force_asr" not in params, (
        "FR-027 violated: 'force_asr' parameter found in collect_transcripts_command."
    )
    # also check typer option names via default values
    for param_name, param in params.items():
        default = param.default
        try:
            import typer
            if isinstance(default, typer.models.OptionInfo):
                option_names = getattr(default, "param_decls", None) or []
                for name in option_names:
                    assert "--force-asr" not in name, (
                        f"FR-027 violated: '--force-asr' found as option name on param '{param_name}'."
                    )
        except (AttributeError, ImportError):
            pass


def test_transcript_export_commands_have_no_force_asr_param() -> None:
    """FR-027: transcript export/export-bulk must not expose --force-asr."""
    import inspect

    from tube_scout.cli.transcript import (
        transcript_export_bulk_typer,
        transcript_export_typer,
    )

    for cmd in (transcript_export_typer, transcript_export_bulk_typer):
        params = inspect.signature(cmd).parameters
        assert "force_asr" not in params, (
            f"FR-027 violated: 'force_asr' parameter found in {cmd.__name__}."
        )
