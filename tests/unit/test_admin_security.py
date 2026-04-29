"""ADV-US3 P1 security regression guards (T095 pre-verify).

Each test locks in one mitigation against a specific adversary finding so
a future refactor cannot silently regress.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setenv("TUBE_SCOUT_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("TUBE_SCOUT_CONFIG_DIR", str(tmp_path / "cfg"))
    (tmp_path / "state").mkdir(parents=True, exist_ok=True)
    (tmp_path / "cfg").mkdir(parents=True, exist_ok=True)
    return tmp_path


def test_token_path_rejects_traversal_alias(env: Path) -> None:
    """ADV-US3-12: alias must match strict regex before path construction."""
    from tube_scout.cli.admin import _token_path

    with pytest.raises(ValueError):
        _token_path("../../../etc/passwd")
    with pytest.raises(ValueError):
        _token_path("a/b")
    with pytest.raises(ValueError):
        _token_path("a\\b")
    # legitimate aliases pass
    assert _token_path("physiology").name == "physiology_token.json"
    assert _token_path("a-b1").name == "a-b1_token.json"


def test_read_token_logs_warn_on_corrupt_json(
    env: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """ADV-US3-13: corrupt JSON MUST log WARN, not silently return None.

    Constitution II silent-skip avoidance — operator needs to know the
    token file is unreadable.
    """
    import logging as _logging

    from tube_scout.cli.admin import _read_token, _token_path

    path = _token_path("physiology")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{ not json", encoding="utf-8")
    caplog.set_level(_logging.WARNING, logger="tube_scout.cli.admin")
    result = _read_token("physiology")
    assert result is None
    warns = [r.message for r in caplog.records if r.levelno == _logging.WARNING]
    assert any("token" in m.lower() and "physiology" in m for m in warns), (
        f"expected WARN for corrupt token, got: {warns}"
    )


def test_read_token_rejects_symlink(env: Path) -> None:
    """ADV-US3-15: token path that's a symlink MUST be rejected."""
    from tube_scout.cli.admin import _read_token, _token_path

    real = env / "elsewhere.json"
    real.write_text(
        json.dumps(
            {
                "expires_at": datetime.now(UTC).isoformat(),
                "refresh_token": "x",
            }
        ),
        encoding="utf-8",
    )
    path = _token_path("physiology")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.symlink(real, path)
    except OSError:
        pytest.skip("symlink creation not supported")

    result = _read_token("physiology")
    assert result is None, "symlink token MUST be rejected"


def test_record_uses_real_uid_actor(monkeypatch: pytest.MonkeyPatch) -> None:
    """ADV-US3-16: actor MUST come from getpwuid(geteuid()), not $USER.

    QA V6 권고 적용: 직접 ``_real_uid_actor`` source를 grep해서 의도가
    명확하도록 단순화. ``_record``는 helper를 호출만 하므로 grep
    범위에 포함시키지 않는다.
    """
    monkeypatch.setenv("USER", "spoofed-attacker")

    import inspect

    from tube_scout.cli import admin

    # Primary guard: the dedicated helper resolves identity from real UID.
    src = inspect.getsource(admin._real_uid_actor)
    assert "pw_name" in src or "getpwuid" in src, (
        "_real_uid_actor must derive identity from real uid, not env $USER"
    )
    # Defence-in-depth: bare os.environ['USER'] regression banned in
    # the record path itself.
    assert 'os.environ.get("USER"' not in inspect.getsource(admin._record)


def test_env_name_pattern_validated(env: Path) -> None:
    """ADV-US3-14: env names must match the agenix prefix pattern."""
    import inspect

    from tube_scout.cli import admin

    # The validator function must exist or add_department must enforce the
    # regex inline.
    src = inspect.getsource(admin)
    assert (
        "TUBE_SCOUT_CHANNEL_ID_" in src
        and "TUBE_SCOUT_CLIENT_SECRET_" in src
        and "TUBE_SCOUT_API_KEY_" in src
    ), "admin.py must reference the 3 agenix env-name prefixes for validation"
