"""Tests for tube_scout.web.paths (T006).

Covers:
- CONFIG_DIR / STATE_DIR / LOG_DIR / LOCK_DIR defaults under $HOME.
- XDG_CONFIG_HOME / XDG_STATE_HOME overrides (XDG path appends /tube-scout).
- TUBE_SCOUT_*_DIR direct overrides (no app suffix, takes precedence over XDG).
- ensure_runtime_dirs creates all four directories with mode 0700.
- Empty inputs to internal helper raise ValueError (Constitution II Fail-Fast).

The test always uses *getter* functions because module-level constants are
evaluated once at import time and would not see env mutations done in
fixtures.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove all path-related env vars so each test starts from defaults."""
    for var in (
        "TUBE_SCOUT_CONFIG_DIR",
        "TUBE_SCOUT_STATE_DIR",
        "TUBE_SCOUT_LOG_DIR",
        "TUBE_SCOUT_LOCK_DIR",
        "XDG_CONFIG_HOME",
        "XDG_STATE_HOME",
    ):
        monkeypatch.delenv(var, raising=False)


def test_get_config_dir_defaults_under_home(clean_env: None) -> None:
    from tube_scout.web import paths

    config = paths.get_config_dir()
    assert config == (Path.home() / ".config" / "tube-scout").resolve()


def test_get_state_dir_defaults_under_home(clean_env: None) -> None:
    from tube_scout.web import paths

    state = paths.get_state_dir()
    assert state == (Path.home() / ".local" / "share" / "tube-scout").resolve()


def test_get_log_dir_defaults_under_state(clean_env: None) -> None:
    from tube_scout.web import paths

    assert paths.get_log_dir() == paths.get_state_dir() / "logs"


def test_get_lock_dir_defaults_under_state(clean_env: None) -> None:
    from tube_scout.web import paths

    assert paths.get_lock_dir() == paths.get_state_dir() / "locks"


def test_xdg_config_home_override_appends_app_name(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("TUBE_SCOUT_CONFIG_DIR", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))

    from tube_scout.web import paths

    assert paths.get_config_dir() == (tmp_path / "xdg" / "tube-scout").resolve()


def test_xdg_state_home_override_appends_app_name(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("TUBE_SCOUT_STATE_DIR", raising=False)
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg-state"))

    from tube_scout.web import paths

    assert paths.get_state_dir() == (tmp_path / "xdg-state" / "tube-scout").resolve()


def test_direct_config_override_used_as_is_no_app_suffix(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    target = tmp_path / "ts-conf-abs"
    monkeypatch.setenv("TUBE_SCOUT_CONFIG_DIR", str(target))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))  # should be ignored

    from tube_scout.web import paths

    assert paths.get_config_dir() == target.resolve()


def test_direct_state_override_takes_precedence_over_xdg(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    target = tmp_path / "ts-state-abs"
    monkeypatch.setenv("TUBE_SCOUT_STATE_DIR", str(target))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg-state"))

    from tube_scout.web import paths

    assert paths.get_state_dir() == target.resolve()


def test_direct_log_dir_override(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    target = tmp_path / "ts-logs"
    monkeypatch.setenv("TUBE_SCOUT_LOG_DIR", str(target))

    from tube_scout.web import paths

    assert paths.get_log_dir() == target.resolve()


def test_direct_lock_dir_override(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    target = tmp_path / "ts-locks"
    monkeypatch.setenv("TUBE_SCOUT_LOCK_DIR", str(target))

    from tube_scout.web import paths

    assert paths.get_lock_dir() == target.resolve()


def test_ensure_runtime_dirs_creates_all_four(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("TUBE_SCOUT_CONFIG_DIR", str(tmp_path / "c"))
    monkeypatch.setenv("TUBE_SCOUT_STATE_DIR", str(tmp_path / "s"))
    monkeypatch.delenv("TUBE_SCOUT_LOG_DIR", raising=False)
    monkeypatch.delenv("TUBE_SCOUT_LOCK_DIR", raising=False)

    from tube_scout.web import paths

    paths.ensure_runtime_dirs()

    assert paths.get_config_dir().is_dir()
    assert paths.get_state_dir().is_dir()
    assert paths.get_log_dir().is_dir()
    assert paths.get_lock_dir().is_dir()


def test_ensure_runtime_dirs_sets_mode_0700(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("TUBE_SCOUT_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("TUBE_SCOUT_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.delenv("TUBE_SCOUT_LOG_DIR", raising=False)
    monkeypatch.delenv("TUBE_SCOUT_LOCK_DIR", raising=False)

    from tube_scout.web import paths

    paths.ensure_runtime_dirs()

    for d in (
        paths.get_config_dir(),
        paths.get_state_dir(),
        paths.get_log_dir(),
        paths.get_lock_dir(),
    ):
        mode = stat.S_IMODE(os.stat(d).st_mode)
        assert mode == 0o700, f"{d} mode={oct(mode)}"


def test_resolve_with_priority_rejects_empty_direct_env() -> None:
    from tube_scout.web import paths

    with pytest.raises(ValueError):
        paths._resolve_with_priority("", "XDG_CONFIG_HOME", ".config")


def test_resolve_with_priority_rejects_empty_xdg_env() -> None:
    from tube_scout.web import paths

    with pytest.raises(ValueError):
        paths._resolve_with_priority("TUBE_SCOUT_CONFIG_DIR", "", ".config")


def test_resolve_with_priority_rejects_empty_fallback() -> None:
    from tube_scout.web import paths

    with pytest.raises(ValueError):
        paths._resolve_with_priority("TUBE_SCOUT_CONFIG_DIR", "XDG_CONFIG_HOME", "")
