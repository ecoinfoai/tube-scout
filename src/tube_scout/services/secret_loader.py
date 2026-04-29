"""OAuth client-secret resolver supporting path AND base64 forms.

idea6 ADR-IDEA6-004: ``services/auth.py`` historically only accepted a
filesystem path via ``TUBE_SCOUT_CLIENT_SECRET``. Operators using
agenix-managed secrets only have the JSON in ``_B64`` form
(``TUBE_SCOUT_CLIENT_SECRET_B64``). This module decodes the base64
payload to a 0o600 tmpfile under ``$XDG_RUNTIME_DIR`` (or ``/tmp``),
registers an ``atexit`` cleanup, and returns a ``Path`` indistinguishable
from the legacy form.

Constitution II Fail-Fast: malformed base64 / non-JSON payload raises
:class:`SecretConfigError` (a :class:`UserFacingError`) immediately —
no silent fallback.
"""

from __future__ import annotations

import atexit
import base64
import json
import logging
import os
import resource
import tempfile
from pathlib import Path

from tube_scout.cli.errors import UserFacingError

ENV_PATH = "TUBE_SCOUT_CLIENT_SECRET"
ENV_B64 = "TUBE_SCOUT_CLIENT_SECRET_B64"

_logger = logging.getLogger(__name__)
_temp_files: list[Path] = []


class SecretConfigError(UserFacingError):
    """Operator-facing error during client-secret resolution."""


def _harden_process() -> None:
    """Apply best-effort A4-9/A4-10/A4-11 hardenings (NFR-IDEA6-003).

    - Suppress core dumps (LimitCORE=0) so secrets cannot leak via
      ``core`` files. systemd-managed deployments override this via
      the unit file but the runtime call is the in-process safety net.
    """
    try:  # pragma: no cover — relies on platform support.
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    except (ValueError, OSError) as exc:  # pragma: no cover
        _logger.warning("RLIMIT_CORE not enforced: %s", exc)


def _runtime_dir() -> Path:
    xdg = os.environ.get("XDG_RUNTIME_DIR")
    if xdg:
        d = Path(xdg) / "tube-scout"
    else:
        _logger.warning(
            "$XDG_RUNTIME_DIR is unset; falling back to /tmp/tube-scout. "
            "Operational hardening (NFR-IDEA6-003) recommends a systemd "
            "unit with `RuntimeDirectory=tube-scout`."
        )
        d = Path("/tmp/tube-scout")  # noqa: S108 — fallback is documented.
    d.mkdir(parents=True, exist_ok=True)
    try:
        d.chmod(0o700)
    except OSError:  # pragma: no cover — non-POSIX runners.
        pass
    return d


def _cleanup_tempfile(path: Path) -> None:
    try:
        if path.exists():
            path.unlink()
    except OSError:  # pragma: no cover
        pass


def _decode_b64_to_tmpfs(payload: str) -> Path:
    try:
        raw = base64.b64decode(payload, validate=True)
    except (ValueError, base64.binascii.Error) as exc:
        raise SecretConfigError(
            message=(
                f"{ENV_B64} is not valid base64: {exc}. "
                "Verify the secret was encoded with `base64 -w0`."
            ),
            next_command=(
                f"export {ENV_B64}=$(base64 -w0 client_secret.json)"
            ),
        ) from exc

    try:
        json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SecretConfigError(
            message=(
                f"{ENV_B64} decoded payload is not valid JSON: {exc}. "
                "The payload must be the literal OAuth client_secret JSON."
            ),
            next_command=(
                "agenix -e tube-scout-client-secret  # re-encrypt with the "
                "JSON contents of the OAuth client_secret file"
            ),
        ) from exc

    runtime = _runtime_dir()
    fd, tmp_str = tempfile.mkstemp(
        prefix="client_secret.", suffix=".json", dir=runtime
    )
    tmp = Path(tmp_str)
    try:
        os.set_inheritable(fd, False)  # A4-9: no fork inheritance.
    except OSError:  # pragma: no cover — non-POSIX runners.
        pass
    with os.fdopen(fd, "wb") as f:
        f.write(raw)
    tmp.chmod(0o600)
    atexit.register(_cleanup_tempfile, tmp)
    _temp_files.append(tmp)
    # A4-11: scrub the env var so subprocesses do not re-decode it.
    os.environ.pop(ENV_B64, None)
    return tmp


def resolve_client_secret_path() -> Path:
    """Return a filesystem path to the OAuth client_secret JSON.

    Resolution order:
        1. ``TUBE_SCOUT_CLIENT_SECRET`` (legacy file path).
        2. ``TUBE_SCOUT_CLIENT_SECRET_B64`` (base64-encoded JSON,
           decoded to a 0o600 tmpfile under ``$XDG_RUNTIME_DIR``).

    Raises:
        SecretConfigError: If neither variable is set, the path is
            missing, or the base64 payload is malformed / non-JSON.
    """
    _harden_process()

    path_env = os.environ.get(ENV_PATH)
    if path_env:
        path = Path(path_env)
        if not path.exists():
            raise SecretConfigError(
                message=(
                    f"{ENV_PATH}={path_env!r} but the file does not exist."
                ),
                next_command=(
                    f"ls -l {path_env}  # verify the path or set "
                    f"{ENV_B64} instead"
                ),
            )
        return path

    b64_env = os.environ.get(ENV_B64)
    if b64_env:
        return _decode_b64_to_tmpfs(b64_env)

    raise SecretConfigError(
        message=(
            f"Neither {ENV_PATH} (file path) nor {ENV_B64} "
            "(base64-encoded JSON) is set."
        ),
        next_command=(
            f"export {ENV_PATH}=/path/to/client_secret.json  # OR  "
            f"export {ENV_B64}=$(base64 -w0 client_secret.json)"
        ),
    )
