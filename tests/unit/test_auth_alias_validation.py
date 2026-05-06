"""RED/GREEN tests for _validate_alias() guard (T_SEC1, S-01 P1).

Validates that every public auth function that converts alias → path
rejects path-traversal and unsafe characters at the entry point.
"""

from __future__ import annotations

import pytest

from tube_scout.cli.errors import UserFacingError
from tube_scout.services.auth import _validate_alias


class TestValidAliases:
    def test_alphanumeric_passes(self) -> None:
        _validate_alias("nursing")

    def test_hyphen_passes(self) -> None:
        _validate_alias("nursing-dept")

    def test_underscore_passes(self) -> None:
        _validate_alias("nursing_dept")

    def test_mixed_case_passes(self) -> None:
        _validate_alias("NursingDept")

    def test_single_char_passes(self) -> None:
        _validate_alias("a")

    def test_max_length_passes(self) -> None:
        _validate_alias("a" * 32)


class TestPathTraversalRejected:
    def test_dotdot_slash_raises(self) -> None:
        with pytest.raises(UserFacingError):
            _validate_alias("../foo")

    def test_slash_raises(self) -> None:
        with pytest.raises(UserFacingError):
            _validate_alias("foo/bar")

    def test_backslash_raises(self) -> None:
        with pytest.raises(UserFacingError):
            _validate_alias("foo\\bar")

    def test_leading_dot_raises(self) -> None:
        with pytest.raises(UserFacingError):
            _validate_alias(".foo")

    def test_absolute_path_raises(self) -> None:
        with pytest.raises(UserFacingError):
            _validate_alias("/etc/passwd")


class TestUnsafeCharsRejected:
    def test_null_byte_raises(self) -> None:
        with pytest.raises(UserFacingError):
            _validate_alias("\x00foo")

    def test_empty_string_raises(self) -> None:
        with pytest.raises(UserFacingError):
            _validate_alias("")

    def test_too_long_raises(self) -> None:
        with pytest.raises(UserFacingError):
            _validate_alias("a" * 33)

    def test_non_ascii_raises(self) -> None:
        with pytest.raises(UserFacingError):
            _validate_alias("nursinа")  # Cyrillic 'a' U+0430

    def test_space_raises(self) -> None:
        with pytest.raises(UserFacingError):
            _validate_alias("foo bar")

    def test_leading_hyphen_raises(self) -> None:
        with pytest.raises(UserFacingError):
            _validate_alias("-foo")


class TestErrorContents:
    def test_error_is_user_facing(self) -> None:
        with pytest.raises(UserFacingError):
            _validate_alias("../evil")

    def test_next_command_is_actionable(self) -> None:
        with pytest.raises(UserFacingError) as exc_info:
            _validate_alias("../evil")
        assert "auth" in exc_info.value.next_command
        assert "--channel" in exc_info.value.next_command

    def test_no_secret_in_message(self) -> None:
        with pytest.raises(UserFacingError) as exc_info:
            _validate_alias("../evil")
        assert "secret" not in exc_info.value.message.lower()
        assert "password" not in exc_info.value.message.lower()
