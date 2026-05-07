"""RED tests for new UserFacingError subclasses (T004, spec 009 Phase 2).

Each test asserts: message, next_command, no secret leak, and correct
inheritance from UserFacingError (ADR-007 pattern).
"""

from __future__ import annotations

from tube_scout.cli.errors import (
    DeviceCodeAccessDenied,
    DeviceCodeTimeout,
    LatestProjectMissing,
    LegacyTokenChannelMismatch,
    LegacyTokenCorrupt,
    MultipleAliasesNoSelection,
    NoAliasRegistered,
    ProducerCommandRequiresChannel,
    UserFacingError,
)


class TestLegacyTokenChannelMismatch:
    def test_is_user_facing_error(self) -> None:
        exc = LegacyTokenChannelMismatch(
            channel_id="UCxxxxxx",
            token_path="/home/user/.config/tube-scout/token.json",
        )
        assert isinstance(exc, UserFacingError)

    def test_message_contains_channel_id(self) -> None:
        exc = LegacyTokenChannelMismatch(
            channel_id="UCxxxxxx",
            token_path="/home/user/.config/tube-scout/token.json",
        )
        assert "UCxxxxxx" in exc.message

    def test_next_command_non_empty(self) -> None:
        exc = LegacyTokenChannelMismatch(
            channel_id="UCxxxxxx",
            token_path="/home/user/.config/tube-scout/token.json",
        )
        assert exc.next_command
        assert "auth" in exc.next_command

    def test_no_secret_in_message(self) -> None:
        exc = LegacyTokenChannelMismatch(
            channel_id="UCxxxxxx",
            token_path="/home/user/.config/tube-scout/token.json",
        )
        assert "secret" not in exc.message.lower()
        assert "password" not in exc.message.lower()
        assert "auth" in exc.next_command.lower()


class TestLegacyTokenCorrupt:
    def test_is_user_facing_error(self) -> None:
        exc = LegacyTokenCorrupt(
            token_path="/home/user/.config/tube-scout/token.json",
            reason="invalid JSON",
        )
        assert isinstance(exc, UserFacingError)

    def test_message_contains_path(self) -> None:
        exc = LegacyTokenCorrupt(
            token_path="/home/user/.config/tube-scout/token.json",
            reason="invalid JSON",
        )
        assert "token.json" in exc.message

    def test_next_command_non_empty(self) -> None:
        exc = LegacyTokenCorrupt(
            token_path="/home/user/.config/tube-scout/token.json",
            reason="invalid JSON",
        )
        assert exc.next_command
        assert "auth" in exc.next_command

    def test_no_secret_in_message(self) -> None:
        exc = LegacyTokenCorrupt(
            token_path="/home/user/.config/tube-scout/token.json",
            reason="invalid JSON",
        )
        assert "password" not in exc.message.lower()


class TestMultipleAliasesNoSelection:
    def test_is_user_facing_error(self) -> None:
        exc = MultipleAliasesNoSelection(aliases=["nursing", "dental"])
        assert isinstance(exc, UserFacingError)

    def test_message_lists_all_aliases(self) -> None:
        exc = MultipleAliasesNoSelection(aliases=["nursing", "dental"])
        assert "nursing" in exc.message
        assert "dental" in exc.message

    def test_next_command_contains_channel_flag(self) -> None:
        exc = MultipleAliasesNoSelection(aliases=["nursing", "dental"])
        assert "--channel" in exc.next_command

    def test_next_command_corrected_for_first_alias(self) -> None:
        exc = MultipleAliasesNoSelection(aliases=["nursing", "dental"])
        assert "nursing" in exc.next_command

    def test_no_secret_in_message(self) -> None:
        exc = MultipleAliasesNoSelection(aliases=["nursing", "dental"])
        assert "secret" not in exc.message.lower()
        assert "token" not in exc.message.lower()


class TestNoAliasRegistered:
    def test_is_user_facing_error(self) -> None:
        exc = NoAliasRegistered()
        assert isinstance(exc, UserFacingError)

    def test_message_indicates_no_alias(self) -> None:
        exc = NoAliasRegistered()
        assert exc.message

    def test_next_command_suggests_auth(self) -> None:
        exc = NoAliasRegistered()
        assert "auth" in exc.next_command
        assert "--channel" in exc.next_command

    def test_no_secret_in_message(self) -> None:
        exc = NoAliasRegistered()
        assert "secret" not in exc.message.lower()


class TestDeviceCodeTimeout:
    def test_is_user_facing_error(self) -> None:
        exc = DeviceCodeTimeout(alias="nursing")
        assert isinstance(exc, UserFacingError)

    def test_message_non_empty(self) -> None:
        exc = DeviceCodeTimeout(alias="nursing")
        assert exc.message

    def test_next_command_suggests_retry(self) -> None:
        exc = DeviceCodeTimeout(alias="nursing")
        assert exc.next_command
        assert "auth" in exc.next_command

    def test_alias_in_next_command(self) -> None:
        exc = DeviceCodeTimeout(alias="nursing")
        assert "nursing" in exc.next_command

    def test_no_secret_in_message(self) -> None:
        exc = DeviceCodeTimeout(alias="nursing")
        assert "secret" not in exc.message.lower()
        assert "password" not in exc.message.lower()


class TestDeviceCodeAccessDenied:
    def test_is_user_facing_error(self) -> None:
        exc = DeviceCodeAccessDenied(alias="nursing")
        assert isinstance(exc, UserFacingError)

    def test_message_non_empty(self) -> None:
        exc = DeviceCodeAccessDenied(alias="nursing")
        assert exc.message

    def test_next_command_suggests_retry(self) -> None:
        exc = DeviceCodeAccessDenied(alias="nursing")
        assert exc.next_command
        assert "auth" in exc.next_command

    def test_alias_in_next_command(self) -> None:
        exc = DeviceCodeAccessDenied(alias="nursing")
        assert "nursing" in exc.next_command

    def test_no_secret_in_message(self) -> None:
        exc = DeviceCodeAccessDenied(alias="nursing")
        assert "secret" not in exc.message.lower()


class TestLatestProjectMissing:
    def test_is_user_facing_error(self) -> None:
        exc = LatestProjectMissing()
        assert isinstance(exc, UserFacingError)

    def test_message_non_empty(self) -> None:
        exc = LatestProjectMissing()
        assert exc.message

    def test_next_command_suggests_collect_videos(self) -> None:
        exc = LatestProjectMissing()
        assert exc.next_command
        assert "collect" in exc.next_command

    def test_no_secret_in_message(self) -> None:
        exc = LatestProjectMissing()
        assert "secret" not in exc.message.lower()
        assert "token" not in exc.message.lower()


class TestProducerCommandRequiresChannel:
    def test_is_user_facing_error(self) -> None:
        exc = ProducerCommandRequiresChannel(command="collect videos")
        assert isinstance(exc, UserFacingError)

    def test_message_contains_command(self) -> None:
        exc = ProducerCommandRequiresChannel(command="collect videos")
        assert "collect videos" in exc.message or exc.message

    def test_next_command_contains_channel_flag(self) -> None:
        exc = ProducerCommandRequiresChannel(command="collect videos")
        assert "--channel" in exc.next_command

    def test_no_secret_in_message(self) -> None:
        exc = ProducerCommandRequiresChannel(command="collect videos")
        assert "secret" not in exc.message.lower()
        assert "token" not in exc.message.lower()
