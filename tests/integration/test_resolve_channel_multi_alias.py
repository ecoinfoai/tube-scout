"""Integration tests for FR-006 multi-alias resolution.

Spec 009 Phase 5 (US3) — T030.

- 0 aliases registered → NoAliasRegistered
- 1 alias registered, no --channel → auto-select with dim notice
- 2+ aliases registered, no --channel → MultipleAliasesNoSelection
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tube_scout.cli.errors import (
    MultipleAliasesNoSelection,
    NoAliasRegistered,
)
from tube_scout.services.auth import resolve_channel_alias


@pytest.fixture
def tokens_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    d = tmp_path / "tokens"
    d.mkdir()
    monkeypatch.setenv("TUBE_SCOUT_TOKENS_DIR", str(d))
    return d


def _registry_entry(alias: str, channel_id: str = "UCabc123") -> dict:
    return {
        "alias": alias,
        "channel_id": channel_id,
        "channel_name": f"{alias} dept",
        "registered_at": "2026-05-01T00:00:00+00:00",
        "last_used_at": "2026-05-01T00:00:00+00:00",
        "token_path": f"/tmp/{alias}.json",
    }


def _write_registry(tokens_dir: Path, aliases: list[str]) -> dict:
    from tube_scout.models.config import ChannelRegistration

    payload = {
        a: _registry_entry(a, channel_id=f"UC{a}").__dict__
        if False
        else _registry_entry(a, channel_id=f"UC{a}")
        for a in aliases
    }
    (tokens_dir / "channels.json").write_text(json.dumps(payload), encoding="utf-8")
    return {a: ChannelRegistration(**v) for a, v in payload.items()}


class TestNoAlias:
    def test_zero_aliases_raises_no_alias_registered(self, tokens_dir: Path) -> None:
        registry = _write_registry(tokens_dir, [])
        with pytest.raises(NoAliasRegistered) as exc_info:
            resolve_channel_alias(None, registry)
        assert exc_info.value.next_command


class TestSingleAlias:
    def test_one_alias_auto_select(self, tokens_dir: Path) -> None:
        registry = _write_registry(tokens_dir, ["nursing"])
        alias = resolve_channel_alias(None, registry)
        assert alias == "nursing"

    def test_one_alias_explicit_match(self, tokens_dir: Path) -> None:
        registry = _write_registry(tokens_dir, ["nursing"])
        assert resolve_channel_alias("nursing", registry) == "nursing"


class TestMultiAlias:
    def test_two_aliases_no_flag_raises(self, tokens_dir: Path) -> None:
        registry = _write_registry(tokens_dir, ["nursing", "physio"])
        with pytest.raises(MultipleAliasesNoSelection) as exc_info:
            resolve_channel_alias(None, registry)
        assert "nursing" in exc_info.value.message
        assert "physio" in exc_info.value.message
        assert exc_info.value.next_command

    def test_two_aliases_explicit_picks(self, tokens_dir: Path) -> None:
        registry = _write_registry(tokens_dir, ["nursing", "physio"])
        assert resolve_channel_alias("physio", registry) == "physio"

    def test_explicit_unregistered_raises(self, tokens_dir: Path) -> None:
        from tube_scout.cli.errors import UserFacingError

        registry = _write_registry(tokens_dir, ["nursing"])
        with pytest.raises(UserFacingError):
            resolve_channel_alias("missing", registry)
