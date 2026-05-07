"""One-shot legacy single-channel token migration.

Spec 009 FR-008 / FR-009 / FR-010. Runs at most once per process,
serialized across processes via ``fcntl.flock`` on
``~/.config/tube-scout/.migration.lock``. Reads
``~/.config/tube-scout/{token,token_forcessl}.json`` (legacy paths from
the pre-idea6 single-channel layout) and either:

- Atomically renames into ``tokens/<alias>.json`` when the legacy
  token's ``channel_id`` matches a registered alias and the legacy file
  is newer than the existing alias token; or
- Unlinks the legacy file in every other case (channel_id mismatch,
  corrupt JSON, recovery failure, older mtime).

After the migration runs, the operator should never see legacy paths
again on this host.
"""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

LEGACY_TOKEN_NAMES: tuple[str, ...] = ("token.json", "token_forcessl.json")
LOCK_FILE_NAME = ".migration.lock"
CACHE_FILE_NAME = ".legacy_token_channel_id_cache.json"
CHANNELS_FILE_RELATIVE = ("tokens", "channels.json")
TOKENS_DIR_NAME = "tokens"

_PROCESSED: set[Path] = set()


def recover_channel_id(
    creds: Any,
    cache_path: Path | None = None,
) -> str | None:
    """Resolve the YouTube ``channel_id`` for a legacy token.

    Args:
        creds: Either a ``Credentials`` instance or a dict of token data
            (``access_token``, ``refresh_token``, ``client_id``,
            ``client_secret``, ``token_uri``, ``scopes``).
        cache_path: Optional cache file location for ``(mtime, channel_id)``
            tuples. Currently unused by callers but reserved for an
            offline cache extension (token_migration.md).

    Returns:
        Channel ID string, or ``None`` when recovery fails (revoked token,
        no channels on the account, network error). Callers MUST treat
        ``None`` as "delete the legacy file".
    """
    try:
        from google.oauth2.credentials import Credentials  # noqa: PLC0415
        from googleapiclient.discovery import build  # noqa: PLC0415
    except ImportError:
        return None

    creds_obj: Credentials
    if isinstance(creds, dict):
        try:
            creds_obj = Credentials.from_authorized_user_info(creds)
        except (ValueError, KeyError, TypeError):
            return None
    else:
        creds_obj = creds

    try:
        yt = build("youtube", "v3", credentials=creds_obj)
        resp = yt.channels().list(mine=True, part="id").execute()
        items = resp.get("items", [])
        if not items:
            return None
        return str(items[0]["id"])
    except Exception:
        return None


def _atomic_replace(src: Path, dst: Path, mode: int = 0o600) -> None:
    """Atomically rename ``src`` into ``dst`` after copying with ``mode`` bits.

    If ``dst`` is a symlink, the symlink itself is replaced (not its target).

    Args:
        src: Source path (existing legacy file).
        dst: Destination path inside the alias tokens directory.
        mode: POSIX permission bits to apply before the rename. Default 0o600.
    """
    dst.parent.mkdir(parents=True, exist_ok=True)
    # Remove an existing symlink so os.rename replaces the path entry, not the
    # symlink's target.  A regular file at dst is handled by os.rename itself.
    if dst.is_symlink():
        dst.unlink()
    fd, tmp_path = tempfile.mkstemp(
        dir=dst.parent, suffix=".tmp", prefix=".migrating_"
    )
    try:
        with open(fd, "wb") as out:
            out.write(src.read_bytes())
        os.chmod(tmp_path, mode)
        os.rename(tmp_path, dst)
    except Exception:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise
    src.unlink()


def _load_channels_registry(channels_path: Path) -> dict[str, dict[str, Any]]:
    """Read ``channels.json`` and return its alias-keyed mapping.

    Args:
        channels_path: Filesystem path to ``tokens/channels.json``.

    Returns:
        Mapping of alias → channel metadata dict. Returns ``{}`` when the
        file is missing or empty (treat as "no channels yet").
    """
    if not channels_path.exists():
        return {}
    raw = channels_path.read_text(encoding="utf-8")
    if not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, dict):
        return {}
    return data


def _alias_for_channel_id(
    registry: dict[str, dict[str, Any]], channel_id: str
) -> str | None:
    """Return the alias whose ``channel_id`` matches ``channel_id``."""
    for alias, entry in registry.items():
        if not isinstance(entry, dict):
            continue
        if entry.get("channel_id") == channel_id:
            return alias
    return None


def _process_legacy_path(
    legacy_path: Path,
    *,
    config_dir: Path,
    cache_path: Path,
) -> None:
    """Migrate or unlink a single legacy token file.

    Raises:
        LegacyTokenCorrupt: Token JSON is corrupt, non-dict, or channel_id
            unrecoverable. File is unlinked before raising.
        LegacyTokenChannelMismatch: Token's channel_id does not match any
            registered alias. File is unlinked before raising.
    """
    from tube_scout.cli.errors import (  # noqa: PLC0415
        LegacyTokenChannelMismatch,
        LegacyTokenCorrupt,
    )

    if not legacy_path.exists():
        return

    raw = legacy_path.read_bytes()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        legacy_path.unlink()
        raise LegacyTokenCorrupt(
            token_path=str(legacy_path),
            reason="JSON decode error",
        )
    if not isinstance(data, dict):
        legacy_path.unlink()
        raise LegacyTokenCorrupt(
            token_path=str(legacy_path),
            reason="top-level value is not a JSON object",
        )

    channel_id = recover_channel_id(data, cache_path)
    if channel_id is None:
        legacy_path.unlink()
        raise LegacyTokenCorrupt(
            token_path=str(legacy_path),
            reason="channel_id could not be recovered (revoked, expired, or no channel)",
        )

    channels_path = config_dir / CHANNELS_FILE_RELATIVE[0] / CHANNELS_FILE_RELATIVE[1]
    registry = _load_channels_registry(channels_path)
    match = _alias_for_channel_id(registry, channel_id)
    if match is None:
        legacy_path.unlink()
        raise LegacyTokenChannelMismatch(
            channel_id=channel_id,
            token_path=str(legacy_path),
        )

    target = config_dir / TOKENS_DIR_NAME / f"{match}.json"
    if target.exists():
        if legacy_path.stat().st_mtime > target.stat().st_mtime:
            _atomic_replace(legacy_path, target)
        else:
            legacy_path.unlink()
    else:
        _atomic_replace(legacy_path, target)


def _try_acquire_flock(
    lock_fd: int, timeout: float, poll_interval: float = 0.1
) -> None:
    """Acquire ``LOCK_EX | LOCK_NB`` on ``lock_fd``, retrying until ``timeout``.

    Raises:
        BlockingIOError: When the lock could not be acquired within budget.
    """
    deadline = time.monotonic() + timeout
    while True:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        except BlockingIOError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(poll_interval)


def run_once(
    *,
    config_dir: Path,
    flock_timeout: float = 10.0,
) -> None:
    """One-shot legacy token migration for a given config directory.

    Args:
        config_dir: Directory holding the legacy ``token*.json`` files
            and ``tokens/`` subdirectory (typically
            ``~/.config/tube-scout``).
        flock_timeout: Seconds to wait for the cross-process advisory
            lock before raising ``UserFacingError``.

    Raises:
        UserFacingError: When the advisory lock cannot be acquired within
            ``flock_timeout`` seconds. Per-file migration errors
            (``LegacyTokenCorrupt``, ``LegacyTokenChannelMismatch``) are
            caught, rendered to stderr, and do not abort the remaining files.
    """
    from tube_scout.cli.errors import UserFacingError  # noqa: PLC0415

    config_dir = Path(config_dir).resolve()
    if config_dir in _PROCESSED:
        return
    _PROCESSED.add(config_dir)

    config_dir.mkdir(parents=True, exist_ok=True)
    lock_path = config_dir / LOCK_FILE_NAME
    lock_path.touch(exist_ok=True)

    cache_path = config_dir / CACHE_FILE_NAME

    with open(lock_path, "w", encoding="utf-8") as lock_fd:
        try:
            _try_acquire_flock(lock_fd.fileno(), timeout=flock_timeout)
        except BlockingIOError as exc:
            raise UserFacingError(
                message=(
                    "Could not acquire migration lock at "
                    f"{lock_path} (another tube-scout process may be running)."
                ),
                next_command="retry the command after the other process exits",
            ) from exc

        try:
            for name in LEGACY_TOKEN_NAMES:
                try:
                    _process_legacy_path(
                        config_dir / name,
                        config_dir=config_dir,
                        cache_path=cache_path,
                    )
                except UserFacingError as migration_err:
                    from tube_scout.cli.errors import render_error  # noqa: PLC0415

                    render_error(migration_err)
            if cache_path.exists():
                cache_path.unlink()
        finally:
            fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)


def reset_for_testing() -> None:
    """Clear the per-process idempotency set. Test helper only."""
    _PROCESSED.clear()
