"""CLI regression baseline for T035-bis (R-10).

T035-bis extracts an internal helper ``_collect_all_for_web`` from
``cli/collect.py``. The public Typer commands (``tube-scout collect ...``)
MUST keep their existing signatures, ``Option`` defaults, and help text so
specs 002/004 + spec 008's CLI-First constitution are preserved.

This baseline runs **before** the refactor and MUST PASS, then is re-run
**after** to prove no regression. Architect ADR-006 R-10 + spec FR-022 +
FR-030.
"""

from __future__ import annotations

import inspect
from typing import Any

import pytest
import typer

from tube_scout.cli.collect import (
    collect_all_command,
    collect_analytics_command,
    collect_bulk_command,
    collect_comments_command,
    collect_retention_command,
    collect_transcripts_command,
    collect_videos_command,
)


def _option_info(cmd: Any, param_name: str) -> typer.models.OptionInfo:
    """Return the Typer ``OptionInfo`` for ``param_name`` on ``cmd``."""
    sig = inspect.signature(cmd)
    param = sig.parameters[param_name]
    assert isinstance(param.default, typer.models.OptionInfo), (
        f"{cmd.__name__}.{param_name} default is not a Typer Option; "
        "extracting helper must not change the public command signature."
    )
    return param.default


@pytest.mark.parametrize(
    "cmd",
    [
        collect_videos_command,
        collect_retention_command,
        collect_comments_command,
        collect_transcripts_command,
        collect_analytics_command,
        collect_all_command,
        collect_bulk_command,
    ],
)
def test_command_keeps_data_dir_and_project_dir_options(cmd: Any) -> None:
    """Every collect command MUST expose ``--data-dir`` and ``--project-dir``."""
    sig = inspect.signature(cmd)
    assert "data_dir" in sig.parameters
    assert "project_dir" in sig.parameters
    data_dir_opt = _option_info(cmd, "data_dir")
    project_dir_opt = _option_info(cmd, "project_dir")
    assert data_dir_opt.default == "./data"
    assert project_dir_opt.default == "./projects"
    assert "--data-dir" in (data_dir_opt.param_decls or ())
    assert "--project-dir" in (project_dir_opt.param_decls or ())


def test_collect_all_signature_preserved() -> None:
    """``collect_all_command`` keeps its 5-Option public signature.

    Spec 002 + 004 callers (``tube-scout collect all --channel ... --force-refresh``)
    rely on these exact names + defaults. After T035-bis refactor the
    helper extraction MUST NOT remove or rename any of them.
    """
    sig = inspect.signature(collect_all_command)
    assert list(sig.parameters) == [
        "data_dir",
        "project_dir",
        "project",
        "force_refresh",
        "channel",
    ]
    force_refresh = _option_info(collect_all_command, "force_refresh")
    assert force_refresh.default is False
    assert "--force-refresh" in (force_refresh.param_decls or ())

    channel = _option_info(collect_all_command, "channel")
    assert channel.default is None
    assert "--channel" in (channel.param_decls or ())


def test_collect_videos_keeps_force_refresh_and_channel() -> None:
    sig = inspect.signature(collect_videos_command)
    assert "force_refresh" in sig.parameters
    assert "channel" in sig.parameters
    force_refresh = _option_info(collect_videos_command, "force_refresh")
    assert force_refresh.default is False
    channel = _option_info(collect_videos_command, "channel")
    assert channel.default is None


def test_collect_analytics_keeps_incremental_flag() -> None:
    sig = inspect.signature(collect_analytics_command)
    assert "incremental" in sig.parameters
    incremental = _option_info(collect_analytics_command, "incremental")
    assert incremental.default is True
    # Boolean Typer options use combined --flag/--no-flag declarations
    assert any(
        "--incremental" in (decl or "") for decl in (incremental.param_decls or ())
    )


def test_collect_retention_keeps_video_id_option() -> None:
    sig = inspect.signature(collect_retention_command)
    assert "video_id" in sig.parameters
    video_id = _option_info(collect_retention_command, "video_id")
    assert video_id.default is None
    assert "--video-id" in (video_id.param_decls or ())


def test_collect_comments_keeps_include_replies_flag() -> None:
    sig = inspect.signature(collect_comments_command)
    assert "include_replies" in sig.parameters
    include_replies = _option_info(collect_comments_command, "include_replies")
    assert include_replies.default is False
    assert "--include-replies" in (include_replies.param_decls or ())


def test_help_strings_preserved() -> None:
    """Help text must round-trip — operators rely on these for muscle memory."""
    data_dir = _option_info(collect_videos_command, "data_dir")
    assert "User data directory" in (data_dir.help or "")
    project_dir = _option_info(collect_videos_command, "project_dir")
    assert "Projects root directory" in (project_dir.help or "")


def test_collect_all_callable_directly_with_kwargs() -> None:
    """``collect_all_command`` is callable as a plain function (not just via Typer).

    The web app may need to invoke it directly when the operator clicks
    "재실행" — the call style mirrors the internal stage iteration already
    in the implementation (see lines 779-810 of collect.py).
    """
    # We don't actually run it (no test config) — only verify it's a real
    # callable with the right return annotation.
    sig = inspect.signature(collect_all_command)
    assert sig.return_annotation is None or sig.return_annotation is type(None)


def test_main_app_registers_collect_subcommands() -> None:
    """The Typer app wiring in cli/main.py MUST keep all 7 collect subcommands."""
    from tube_scout.cli import main as cli_main

    # collect_app is a Typer instance with registered_commands list
    registered_names = {
        cmd.name for cmd in cli_main.collect_app.registered_commands
    }
    assert {
        "videos",
        "retention",
        "comments",
        "transcripts",
        "analytics",
        "bulk",
        "all",
    } <= registered_names
