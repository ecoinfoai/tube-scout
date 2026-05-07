"""RED tests for resolve_channel_alias helper (T005, spec 009 Phase 2).

Covers: explicit-valid, explicit-invalid (raises), zero-alias (raises
NoAliasRegistered), one-alias (auto-select + dim notice), multi-alias
(raises MultipleAliasesNoSelection with corrected commands).
"""

from __future__ import annotations

import pytest

from tube_scout.cli.errors import (
    MultipleAliasesNoSelection,
    NoAliasRegistered,
    UserFacingError,
)
from tube_scout.models.config import ChannelRegistration
from tube_scout.services.auth import resolve_channel_alias


def _make_reg(alias: str, channel_id: str = "UCxxxxxx") -> ChannelRegistration:
    return ChannelRegistration(
        alias=alias,
        channel_id=channel_id,
        channel_name=alias.capitalize(),
        registered_at="2026-01-01T00:00:00",
        last_used_at="2026-01-01T00:00:00",
        token_path=f"tokens/{alias}.json",
    )


class TestResolveChannelAliasExplicit:
    def test_explicit_valid_alias_returns_alias(self) -> None:
        registry = {"nursing": _make_reg("nursing")}
        result = resolve_channel_alias("nursing", registry)
        assert result == "nursing"

    def test_explicit_invalid_alias_raises_user_facing_error(self) -> None:
        registry = {"nursing": _make_reg("nursing")}
        with pytest.raises(UserFacingError) as exc_info:
            resolve_channel_alias("dental", registry)
        assert (
            "dental" in exc_info.value.message
            or "dental" in exc_info.value.next_command
        )

    def test_explicit_invalid_alias_next_command_contains_channel_flag(self) -> None:
        registry = {"nursing": _make_reg("nursing")}
        with pytest.raises(UserFacingError) as exc_info:
            resolve_channel_alias("unknown", registry)
        assert "--channel" in exc_info.value.next_command


class TestResolveChannelAliasZero:
    def test_zero_alias_raises_no_alias_registered(self) -> None:
        with pytest.raises(NoAliasRegistered):
            resolve_channel_alias(None, {})

    def test_zero_alias_error_is_user_facing(self) -> None:
        with pytest.raises(UserFacingError):
            resolve_channel_alias(None, {})

    def test_zero_alias_next_command_suggests_auth(self) -> None:
        with pytest.raises(NoAliasRegistered) as exc_info:
            resolve_channel_alias(None, {})
        assert "auth" in exc_info.value.next_command
        assert "--channel" in exc_info.value.next_command


class TestResolveChannelAliasOneAlias:
    def test_one_alias_auto_selects(self) -> None:
        registry = {"nursing": _make_reg("nursing")}
        result = resolve_channel_alias(None, registry)
        assert result == "nursing"

    def test_one_alias_returns_str(self) -> None:
        registry = {"dental": _make_reg("dental", channel_id="UCyyyyyy")}
        result = resolve_channel_alias(None, registry)
        assert isinstance(result, str)
        assert result == "dental"


class TestResolveChannelAliasMultiAlias:
    def test_multi_alias_raises_multiple_aliases_no_selection(self) -> None:
        registry = {
            "nursing": _make_reg("nursing", channel_id="UCaaaaaa"),
            "dental": _make_reg("dental", channel_id="UCbbbbbb"),
        }
        with pytest.raises(MultipleAliasesNoSelection):
            resolve_channel_alias(None, registry)

    def test_multi_alias_error_is_user_facing(self) -> None:
        registry = {
            "nursing": _make_reg("nursing"),
            "dental": _make_reg("dental"),
        }
        with pytest.raises(UserFacingError):
            resolve_channel_alias(None, registry)

    def test_multi_alias_message_lists_both_aliases(self) -> None:
        registry = {
            "nursing": _make_reg("nursing"),
            "dental": _make_reg("dental"),
        }
        with pytest.raises(MultipleAliasesNoSelection) as exc_info:
            resolve_channel_alias(None, registry)
        assert "nursing" in exc_info.value.message
        assert "dental" in exc_info.value.message

    def test_multi_alias_next_command_has_channel_flag(self) -> None:
        registry = {
            "nursing": _make_reg("nursing"),
            "dental": _make_reg("dental"),
        }
        with pytest.raises(MultipleAliasesNoSelection) as exc_info:
            resolve_channel_alias(None, registry)
        assert "--channel" in exc_info.value.next_command

    def test_three_aliases_all_listed_in_message(self) -> None:
        registry = {
            "nursing": _make_reg("nursing"),
            "dental": _make_reg("dental"),
            "pharmacy": _make_reg("pharmacy"),
        }
        with pytest.raises(MultipleAliasesNoSelection) as exc_info:
            resolve_channel_alias(None, registry)
        msg = exc_info.value.message
        assert "nursing" in msg
        assert "dental" in msg
        assert "pharmacy" in msg
