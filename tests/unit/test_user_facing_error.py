"""RED then GREEN: cli.errors.UserFacingError + render_error.

Spec: idea6 / FR-IDEA6-007 / ADR-IDEA6-007 / T-IDEA6-G1.

Every user-facing failure path raises ``UserFacingError`` carrying a
``next_command`` hint. ``render_error`` formats the exception to stderr
in the canonical "Error: <msg>\\n  Try: <next_command>" form, then the
caller propagates a non-zero exit.
"""

from __future__ import annotations

import pytest


class TestUserFacingError:
    def test_imports(self) -> None:
        from tube_scout.cli.errors import UserFacingError

        exc = UserFacingError(message="hello", next_command="tube-scout x y")
        assert exc.message == "hello"
        assert exc.next_command == "tube-scout x y"

    def test_str_includes_message(self) -> None:
        from tube_scout.cli.errors import UserFacingError

        exc = UserFacingError(message="boom", next_command="tube-scout fix")
        assert "boom" in str(exc)

    def test_next_command_required(self) -> None:
        """``next_command`` is mandatory — Constitution II Fail-Fast."""
        from tube_scout.cli.errors import UserFacingError

        with pytest.raises(TypeError):
            UserFacingError(message="missing hint")  # type: ignore[call-arg]


class TestRenderError:
    def test_render_writes_stderr(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from tube_scout.cli.errors import UserFacingError, render_error

        exc = UserFacingError(
            message="parsed_titles.json not found",
            next_command="tube-scout analyze parse-titles --channel nursing",
        )
        render_error(exc)
        captured = capsys.readouterr()
        assert "parsed_titles.json not found" in captured.err
        assert "Try: tube-scout analyze parse-titles --channel nursing" in captured.err

    def test_render_accepts_subclass(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from tube_scout.cli.errors import UserFacingError, render_error

        class TokenScopeError(UserFacingError):
            pass

        exc = TokenScopeError(
            message="missing youtube.force-ssl scope",
            next_command="tube-scout auth --revoke nursing && tube-scout auth --channel nursing",
        )
        render_error(exc)
        captured = capsys.readouterr()
        assert "missing youtube.force-ssl scope" in captured.err
        assert "Try:" in captured.err
