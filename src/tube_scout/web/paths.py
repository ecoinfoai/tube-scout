"""Filesystem path resolution for the admin web UI.

Resolves base directories with a three-tier priority chain so that systemd
units running with ``ProtectHome=true`` can redirect storage outside the home
tree via ``EnvironmentFile``.

Priority (highest first):
    1. ``TUBE_SCOUT_CONFIG_DIR`` / ``TUBE_SCOUT_STATE_DIR`` (absolute path,
       used as-is — does NOT append ``/tube-scout``).
    2. ``XDG_CONFIG_HOME`` / ``XDG_STATE_HOME`` (appends ``/tube-scout``).
    3. ``$HOME/.config`` or ``$HOME/.local/share`` (appends ``/tube-scout``).

Logs and lock files default to ``${STATE_DIR}/{logs,locks}`` and accept the
direct overrides ``TUBE_SCOUT_LOG_DIR`` / ``TUBE_SCOUT_LOCK_DIR``.
"""

from __future__ import annotations

import os
from pathlib import Path

_APP_NAME = "tube-scout"


def _resolve_with_priority(
    direct_env: str,
    xdg_env: str,
    home_relative_fallback: str,
) -> Path:
    """Resolve a base directory using the three-tier priority chain.

    Args:
        direct_env: Direct override env var name (e.g. ``TUBE_SCOUT_CONFIG_DIR``).
            When set, the value is used as the absolute target without
            appending the app name. Intended for systemd ``ProtectHome=true``
            deployments that bind state into a non-home location.
        xdg_env: XDG base-dir env var name (e.g. ``XDG_CONFIG_HOME``).
            When set, ``${value}/tube-scout`` is returned.
        home_relative_fallback: Path relative to ``$HOME`` used when neither
            override is present (e.g. ``.config``). ``/tube-scout`` is appended.

    Returns:
        Absolute :class:`Path`. Not created on disk.

    Raises:
        ValueError: If any argument is empty.
    """
    if not direct_env:
        raise ValueError("direct_env must be a non-empty string")
    if not xdg_env:
        raise ValueError("xdg_env must be a non-empty string")
    if not home_relative_fallback:
        raise ValueError("home_relative_fallback must be a non-empty string")
    direct = os.environ.get(direct_env)
    if direct:
        return Path(direct).expanduser().resolve()
    xdg = os.environ.get(xdg_env)
    if xdg:
        return (Path(xdg).expanduser() / _APP_NAME).resolve()
    return (Path.home() / home_relative_fallback / _APP_NAME).resolve()


def _resolve_config_dir() -> Path:
    return _resolve_with_priority("TUBE_SCOUT_CONFIG_DIR", "XDG_CONFIG_HOME", ".config")


def _resolve_state_dir() -> Path:
    return _resolve_with_priority(
        "TUBE_SCOUT_STATE_DIR", "XDG_STATE_HOME", ".local/share"
    )


def _resolve_log_dir() -> Path:
    direct = os.environ.get("TUBE_SCOUT_LOG_DIR")
    if direct:
        return Path(direct).expanduser().resolve()
    return _resolve_state_dir() / "logs"


def _resolve_lock_dir() -> Path:
    direct = os.environ.get("TUBE_SCOUT_LOCK_DIR")
    if direct:
        return Path(direct).expanduser().resolve()
    return _resolve_state_dir() / "locks"


def get_config_dir() -> Path:
    """Return the user-config directory for tube-scout."""
    return _resolve_config_dir()


def get_state_dir() -> Path:
    """Return the runtime-state directory for tube-scout."""
    return _resolve_state_dir()


def get_log_dir() -> Path:
    """Return the log directory (``${STATE_DIR}/logs`` unless overridden)."""
    return _resolve_log_dir()


def get_lock_dir() -> Path:
    """Return the directory housing per-department ``flock`` files."""
    return _resolve_lock_dir()


def ensure_runtime_dirs() -> None:
    """Create config/state/log/lock directories with mode 0700.

    Idempotent. Called on app startup (lifespan) before any persistence
    happens. Restrictive permissions enforce the SQLite-file 0600 expectation
    in the data-model.
    """
    for directory in (get_config_dir(), get_state_dir(), get_log_dir(), get_lock_dir()):
        directory.mkdir(parents=True, exist_ok=True)
        try:
            directory.chmod(0o700)
        except PermissionError:
            # intentional-skip: chmod can fail on tmpfs / CI bind-mounts;
            # the directory already exists with whatever perms upstream set.
            pass


CONFIG_DIR: Path = _resolve_config_dir()
STATE_DIR: Path = _resolve_state_dir()
LOG_DIR: Path = _resolve_log_dir()
LOCK_DIR: Path = _resolve_lock_dir()
