"""Tests for app lifespan env-var validation (T018 RED).

Covers (Constitution II Fail-Fast):
- ``create_app()`` lifespan startup raises when any required env var is missing
- All three required vars are checked: TUBE_SCOUT_ADMIN_USERNAME,
  TUBE_SCOUT_ADMIN_PASSWORD_BCRYPT, TUBE_SCOUT_SESSION_SECRET
- Empty value also rejected (treated like missing)
- All three present → app boots cleanly
- Validation message names the offending env var (no value leak)

Targets ``tube_scout.web.app`` — implementation pending (T036).
"""

from __future__ import annotations

import bcrypt
import pytest


REQUIRED_ENVS = [
    "TUBE_SCOUT_ADMIN_USERNAME",
    "TUBE_SCOUT_ADMIN_PASSWORD_BCRYPT",
    "TUBE_SCOUT_SESSION_SECRET",
]


def _set_all_required(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("TUBE_SCOUT_ADMIN_USERNAME", "ops")
    pw_hash = bcrypt.hashpw(b"S3cret!", bcrypt.gensalt(rounds=4)).decode()
    monkeypatch.setenv("TUBE_SCOUT_ADMIN_PASSWORD_BCRYPT", pw_hash)
    monkeypatch.setenv("TUBE_SCOUT_SESSION_SECRET", "x" * 32)
    monkeypatch.setenv("TUBE_SCOUT_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("TUBE_SCOUT_CONFIG_DIR", str(tmp_path / "cfg"))


@pytest.mark.parametrize("missing", REQUIRED_ENVS)
def test_missing_required_env_fails_lifespan(
    monkeypatch: pytest.MonkeyPatch, tmp_path, missing: str
) -> None:
    from tube_scout.web import app as web_app

    _set_all_required(monkeypatch, tmp_path)
    monkeypatch.delenv(missing, raising=False)

    with pytest.raises(web_app.MissingEnvError) as exc:
        web_app.validate_required_env()
    assert missing in str(exc.value)


@pytest.mark.parametrize("empty", REQUIRED_ENVS)
def test_empty_required_env_fails_lifespan(
    monkeypatch: pytest.MonkeyPatch, tmp_path, empty: str
) -> None:
    from tube_scout.web import app as web_app

    _set_all_required(monkeypatch, tmp_path)
    monkeypatch.setenv(empty, "")

    with pytest.raises(web_app.MissingEnvError) as exc:
        web_app.validate_required_env()
    assert empty in str(exc.value)


def test_all_required_present_validates_ok(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    from tube_scout.web import app as web_app

    _set_all_required(monkeypatch, tmp_path)
    web_app.validate_required_env()


def test_missing_env_message_does_not_leak_value(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """When TUBE_SCOUT_ADMIN_PASSWORD_BCRYPT is set but malformed, the error
    must mention the env var name only — never include the value (would leak
    a partial bcrypt hash)."""
    from tube_scout.web import app as web_app

    _set_all_required(monkeypatch, tmp_path)
    bogus_hash = "$2b$12$LEAKLEAKLEAKLEAKLEAKLEAKLEAKLEAKLEAK"
    monkeypatch.setenv("TUBE_SCOUT_ADMIN_PASSWORD_BCRYPT", bogus_hash)

    with pytest.raises(Exception) as exc:
        web_app.validate_required_env()
    assert "LEAK" not in str(exc.value)
