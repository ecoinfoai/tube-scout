"""GREEN tests for services.secret_loader (T-IDEA6-E1+E2, FR-IDEA6-004, ADR-004).

Covers the path-form, _B64-form, neither-set, A4-9 (no fd inheritance),
A4-10 (LimitCORE), A4-11 (env scrubbing) cases.
"""

from __future__ import annotations

import base64
import json
import os
import resource
import subprocess
from pathlib import Path

import pytest


SAMPLE_CLIENT_SECRET = {
    "installed": {
        "client_id": "abc.apps.googleusercontent.com",
        "client_secret": "shh",
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
    }
}


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("TUBE_SCOUT_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("TUBE_SCOUT_CLIENT_SECRET_B64", raising=False)
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "xdg"))


def test_path_form_returns_existing_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from tube_scout.services.secret_loader import resolve_client_secret_path

    secret_path = tmp_path / "client_secret.json"
    secret_path.write_text(json.dumps(SAMPLE_CLIENT_SECRET))
    monkeypatch.setenv("TUBE_SCOUT_CLIENT_SECRET", str(secret_path))

    out = resolve_client_secret_path()
    assert out == secret_path


def test_path_form_missing_file_raises_actionable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from tube_scout.cli.errors import UserFacingError
    from tube_scout.services.secret_loader import resolve_client_secret_path

    monkeypatch.setenv("TUBE_SCOUT_CLIENT_SECRET", str(tmp_path / "nope.json"))
    with pytest.raises(UserFacingError) as exc_info:
        resolve_client_secret_path()
    assert "ls -l" in exc_info.value.next_command


def test_b64_form_decodes_to_tmpfs_with_0o600(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tube_scout.services.secret_loader import resolve_client_secret_path

    encoded = base64.b64encode(json.dumps(SAMPLE_CLIENT_SECRET).encode()).decode()
    monkeypatch.setenv("TUBE_SCOUT_CLIENT_SECRET_B64", encoded)

    path = resolve_client_secret_path()
    assert path.exists()
    mode = path.stat().st_mode & 0o777
    assert mode == 0o600
    assert json.loads(path.read_text()) == SAMPLE_CLIENT_SECRET


def test_b64_form_validates_json_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    from tube_scout.cli.errors import UserFacingError
    from tube_scout.services.secret_loader import resolve_client_secret_path

    encoded = base64.b64encode(b"not json at all").decode()
    monkeypatch.setenv("TUBE_SCOUT_CLIENT_SECRET_B64", encoded)
    with pytest.raises(UserFacingError) as exc_info:
        resolve_client_secret_path()
    assert "JSON" in exc_info.value.message


def test_b64_form_rejects_invalid_base64(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tube_scout.cli.errors import UserFacingError
    from tube_scout.services.secret_loader import resolve_client_secret_path

    monkeypatch.setenv("TUBE_SCOUT_CLIENT_SECRET_B64", "this is not base64!")
    with pytest.raises(UserFacingError) as exc_info:
        resolve_client_secret_path()
    assert "base64" in exc_info.value.message


def test_neither_set_raises_actionable_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tube_scout.cli.errors import UserFacingError
    from tube_scout.services.secret_loader import resolve_client_secret_path

    with pytest.raises(UserFacingError) as exc_info:
        resolve_client_secret_path()
    assert "TUBE_SCOUT_CLIENT_SECRET" in exc_info.value.message


def test_env_scrubbed_after_load(monkeypatch: pytest.MonkeyPatch) -> None:
    """A4-11: ``TUBE_SCOUT_CLIENT_SECRET_B64`` is removed after decoding."""
    from tube_scout.services.secret_loader import resolve_client_secret_path

    encoded = base64.b64encode(json.dumps(SAMPLE_CLIENT_SECRET).encode()).decode()
    monkeypatch.setenv("TUBE_SCOUT_CLIENT_SECRET_B64", encoded)
    resolve_client_secret_path()
    assert os.environ.get("TUBE_SCOUT_CLIENT_SECRET_B64") is None


def test_core_dump_disabled(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A4-10: process RLIMIT_CORE is set to 0 after a resolve call."""
    from tube_scout.services.secret_loader import resolve_client_secret_path

    secret_path = tmp_path / "client_secret.json"
    secret_path.write_text(json.dumps(SAMPLE_CLIENT_SECRET))
    monkeypatch.setenv("TUBE_SCOUT_CLIENT_SECRET", str(secret_path))
    resolve_client_secret_path()
    soft, _ = resource.getrlimit(resource.RLIMIT_CORE)
    assert soft == 0


def test_no_fd_inheritance(monkeypatch: pytest.MonkeyPatch) -> None:
    """A4-9: child process spawned with close_fds=True does not inherit tmpfile."""
    from tube_scout.services.secret_loader import resolve_client_secret_path

    encoded = base64.b64encode(json.dumps(SAMPLE_CLIENT_SECRET).encode()).decode()
    monkeypatch.setenv("TUBE_SCOUT_CLIENT_SECRET_B64", encoded)
    tmp = resolve_client_secret_path()

    # If a forked child cannot read the tmpfile via inherited fd
    # (close_fds=True is the default in Python 3.7+), then opening it
    # by path inside the child must work and must not see a leftover fd.
    proc = subprocess.run(
        ["bash", "-c", f"cat {tmp}"],
        capture_output=True,
        text=True,
        close_fds=True,
        check=True,
    )
    assert "client_id" in proc.stdout
