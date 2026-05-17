"""Unit tests for collect_ingest_command B-9 alias boundary (spec 017 adversary T-17/T-18 fix).

Fix #3: CLI layer now fails explicitly when alias is absent from BOTH registries.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch


def _get_runner_and_app():
    from typer.testing import CliRunner

    from tube_scout.cli.main import app
    return CliRunner(), app


def _make_archive(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def test_alias_absent_both_registries_exits_1(tmp_path: Path) -> None:
    """CLI exits 1 when alias is absent from both channels.json and departments.json (Fix T-17/T-18)."""
    archive = _make_archive(tmp_path / "archive")

    runner, app = _get_runner_and_app()
    with patch(
        "tube_scout.services.auth.load_registry",
        return_value={},
    ), patch(
        "tube_scout.web.repo.departments_repo.DepartmentsRepo.list_all",
        return_value=[],
    ):
        result = runner.invoke(app, [
            "collect", "ingest",
            "--takeout-dir", str(archive),
            "--channel", "ghost_alias",
        ])

    assert result.exit_code == 1, (
        f"Expected exit 1 when alias absent from both registries, "
        f"got {result.exit_code}\n{result.output}"
    )
    assert "not registered" in result.output, (
        f"Expected 'not registered' message, got: {result.output}"
    )


def test_alias_in_channels_only_proceeds(tmp_path: Path) -> None:
    """Alias present only in channels.json (not departments.json) does not block at CLI layer."""
    archive = _make_archive(tmp_path / "archive")

    runner, app = _get_runner_and_app()
    ch_reg = MagicMock()
    ch_reg.channel_id = "UCtest001"
    with patch(
        "tube_scout.services.auth.load_registry",
        return_value={"nursing": ch_reg},
    ), patch(
        "tube_scout.web.repo.departments_repo.DepartmentsRepo.list_all",
        return_value=[],
    ), patch(
        "tube_scout.services.unified_ingest.ingest_unified",
        side_effect=ValueError("alias not registered"),
    ):
        result = runner.invoke(app, [
            "collect", "ingest",
            "--takeout-dir", str(archive),
            "--channel", "nursing",
        ])

    # CLI B-9 check passes (one-sided registration is not CLI-level blocked)
    # Service layer raises ValueError → exit 1 via except ValueError handler
    assert result.exit_code == 1, (
        f"Expected exit 1 from service layer ValueError, got {result.exit_code}\n{result.output}"
    )
    assert "not registered" in result.output, (
        f"Expected service-layer error message, got: {result.output}"
    )
