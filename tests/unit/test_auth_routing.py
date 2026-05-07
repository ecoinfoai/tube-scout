"""RED unit tests for build_*_client(alias) routing (T012).

Tests that build_analytics_client(alias) and build_reporting_client(alias)
accept an alias parameter and route through authenticate_channel(alias),
and NEVER read ~/.config/tube-scout/token.json (the legacy single-channel path).

All tests MUST fail (TypeError / unexpected behavior) until T017 refactors
src/tube_scout/services/auth.py to add alias parameter.

FR: FR-007 (alias-keyed token routing)
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


class TestBuildAnalyticsClientAliasParam:
    def test_build_analytics_client_accepts_alias(self) -> None:
        from tube_scout.services.auth import build_analytics_client  # noqa: PLC0415

        with patch("tube_scout.services.auth.authenticate_channel") as mock_auth:
            mock_auth.return_value = MagicMock()
            with patch("tube_scout.services.auth.build") as mock_build:
                mock_build.return_value = MagicMock()
                build_analytics_client(alias="nursing")
        mock_auth.assert_called_once_with("nursing")

    def test_build_analytics_client_routes_to_authenticate_channel(self) -> None:
        from tube_scout.services.auth import build_analytics_client  # noqa: PLC0415

        calls = []
        with patch(
            "tube_scout.services.auth.authenticate_channel",
            side_effect=lambda a: calls.append(a) or MagicMock(),
        ):
            with patch("tube_scout.services.auth.build", return_value=MagicMock()):
                build_analytics_client(alias="nursing")
        assert "nursing" in calls

    def test_build_analytics_client_never_reads_legacy_token_json(
        self, tmp_path: Path
    ) -> None:
        """T012 contract: alias routing MUST NOT fall through to token.json."""
        from tube_scout.services.auth import build_analytics_client  # noqa: PLC0415

        legacy_token = tmp_path / "token.json"
        legacy_token.write_text('{"token": "legacy"}')

        reads: list[Path] = []
        original_open = open

        def tracking_open(path, *args, **kwargs):
            p = Path(path)
            if p.name == "token.json":
                reads.append(p)
            return original_open(path, *args, **kwargs)

        with patch(
            "tube_scout.services.auth.authenticate_channel", return_value=MagicMock()
        ):
            with patch("tube_scout.services.auth.build", return_value=MagicMock()):
                with patch("builtins.open", side_effect=tracking_open):
                    build_analytics_client(alias="nursing")

        token_json_reads = [
            r for r in reads if "tube-scout" in str(r) or r == legacy_token
        ]
        assert len(token_json_reads) == 0, (
            f"Unexpected token.json read: {token_json_reads}"
        )


class TestBuildReportingClientAliasParam:
    def test_build_reporting_client_accepts_alias(self) -> None:
        from tube_scout.services.auth import build_reporting_client  # noqa: PLC0415

        with patch("tube_scout.services.auth.authenticate_channel") as mock_auth:
            mock_auth.return_value = MagicMock()
            with patch("tube_scout.services.auth.build") as mock_build:
                mock_build.return_value = MagicMock()
                build_reporting_client(alias="nursing")
        mock_auth.assert_called_once_with("nursing")

    def test_build_reporting_client_routes_to_authenticate_channel(self) -> None:
        from tube_scout.services.auth import build_reporting_client  # noqa: PLC0415

        calls = []
        with patch(
            "tube_scout.services.auth.authenticate_channel",
            side_effect=lambda a: calls.append(a) or MagicMock(),
        ):
            with patch("tube_scout.services.auth.build", return_value=MagicMock()):
                build_reporting_client(alias="nursing")
        assert "nursing" in calls

    def test_build_reporting_client_never_reads_legacy_token_json(
        self, tmp_path: Path
    ) -> None:
        from tube_scout.services.auth import build_reporting_client  # noqa: PLC0415

        reads: list[Path] = []
        original_open = open

        def tracking_open(path, *args, **kwargs):
            p = Path(str(path))
            if p.name == "token.json":
                reads.append(p)
            return original_open(path, *args, **kwargs)

        with patch(
            "tube_scout.services.auth.authenticate_channel", return_value=MagicMock()
        ):
            with patch("tube_scout.services.auth.build", return_value=MagicMock()):
                with patch("builtins.open", side_effect=tracking_open):
                    build_reporting_client(alias="nursing")

        token_json_reads = [r for r in reads if "tube-scout" in str(r)]
        assert len(token_json_reads) == 0, (
            f"Unexpected token.json read: {token_json_reads}"
        )


class TestAliasValidationInRouting:
    def test_build_analytics_client_rejects_invalid_alias(self) -> None:
        from tube_scout.cli.errors import UserFacingError  # noqa: PLC0415
        from tube_scout.services.auth import build_analytics_client  # noqa: PLC0415

        with pytest.raises(UserFacingError):
            build_analytics_client(alias="../evil")

    def test_build_reporting_client_rejects_invalid_alias(self) -> None:
        from tube_scout.cli.errors import UserFacingError  # noqa: PLC0415
        from tube_scout.services.auth import build_reporting_client  # noqa: PLC0415

        with pytest.raises(UserFacingError):
            build_reporting_client(alias="../evil")

    def test_build_analytics_client_rejects_empty_alias(self) -> None:
        from tube_scout.cli.errors import UserFacingError  # noqa: PLC0415
        from tube_scout.services.auth import build_analytics_client  # noqa: PLC0415

        with pytest.raises(UserFacingError):
            build_analytics_client(alias="")
