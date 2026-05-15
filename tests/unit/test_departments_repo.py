"""Tests for tube_scout.web.repo.departments_repo (T007 RED).

Covers:
- Atomic write to ``departments.json`` (no partial file on crash).
- Pydantic schema validation on read (alias regex, env-var name regex).
- Duplicate alias rejection (ValueError or domain-specific error).
- Mtime-based cache invalidation: subsequent loads skip JSON parse if mtime
  unchanged, but pick up updates when the file is rewritten.

Per Constitution I (RED first), these tests are authored against the
not-yet-implemented module ``tube_scout.web.repo.departments_repo``. They are
expected to fail with ImportError until T022 lands the module.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest


def _sample_dept_dict(alias: str = "physiology", display: str = "물리치료과") -> dict:
    return {
        "alias": alias,
        "display_name": display,
        "channel_id_env": f"TUBE_SCOUT_CHANNEL_ID_{alias.upper()}",
        "client_secret_env": f"TUBE_SCOUT_CLIENT_SECRET_{alias.upper()}",
        "api_key_env": f"TUBE_SCOUT_API_KEY_{alias.upper()}",
        "registered_at": datetime.now(UTC).isoformat(),
        "last_used_at": None,
    }


@pytest.fixture
def repo_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Redirect CONFIG_DIR to ``tmp_path`` and return the JSON file path."""
    monkeypatch.setenv("TUBE_SCOUT_CONFIG_DIR", str(tmp_path))
    monkeypatch.delenv("TUBE_SCOUT_TOKENS_DIR", raising=False)
    return tmp_path / "departments.json"


def test_load_returns_empty_list_when_file_absent(repo_path: Path) -> None:
    from tube_scout.web.repo import departments_repo

    repo = departments_repo.DepartmentsRepo()
    assert repo.list_all() == []


def test_save_then_load_roundtrips_one_department(repo_path: Path) -> None:
    from tube_scout.web.repo import departments_repo

    repo = departments_repo.DepartmentsRepo()
    repo.add(_sample_dept_dict())
    loaded = departments_repo.DepartmentsRepo().list_all()
    assert len(loaded) == 1
    assert loaded[0].alias == "physiology"
    assert loaded[0].display_name == "물리치료과"


def test_atomic_write_no_partial_file_on_crash(
    repo_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Atomic write: a failure between tmp-write and rename leaves the original
    file untouched (no half-written corruption)."""
    from tube_scout.web.repo import departments_repo

    repo = departments_repo.DepartmentsRepo()
    repo.add(_sample_dept_dict("physiology"))

    original_bytes = repo_path.read_bytes()

    def explode(*_a: object, **_kw: object) -> None:
        raise RuntimeError("simulated crash before rename")

    monkeypatch.setattr(departments_repo.os, "replace", explode)

    with pytest.raises(RuntimeError):
        repo.add(_sample_dept_dict("nursing"))

    # Original file unchanged; no .tmp left dangling that breaks load.
    assert repo_path.read_bytes() == original_bytes
    repo2 = departments_repo.DepartmentsRepo()
    assert {d.alias for d in repo2.list_all()} == {"physiology"}


def test_duplicate_alias_rejected(repo_path: Path) -> None:
    from tube_scout.web.repo import departments_repo

    repo = departments_repo.DepartmentsRepo()
    repo.add(_sample_dept_dict("physiology"))
    with pytest.raises(departments_repo.DuplicateAliasError):
        repo.add(_sample_dept_dict("physiology", display="물리치료과B"))


def test_invalid_alias_pattern_rejected(repo_path: Path) -> None:
    from tube_scout.web.repo import departments_repo

    repo = departments_repo.DepartmentsRepo()
    bad = _sample_dept_dict("Bad-Alias")  # uppercase not allowed
    with pytest.raises(Exception):
        repo.add(bad)


def test_invalid_env_var_name_rejected(repo_path: Path) -> None:
    from tube_scout.web.repo import departments_repo

    repo = departments_repo.DepartmentsRepo()
    bad = _sample_dept_dict("ok")
    bad["channel_id_env"] = "WRONG_PREFIX_FOO"
    with pytest.raises(Exception):
        repo.add(bad)


def test_mtime_cache_avoids_reparsing(
    repo_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tube_scout.web.repo import departments_repo

    repo = departments_repo.DepartmentsRepo()
    repo.add(_sample_dept_dict("physiology"))

    parse_calls = {"n": 0}
    real_loads = json.loads

    def counting_loads(s: str | bytes, *a: object, **kw: object) -> object:
        parse_calls["n"] += 1
        return real_loads(s, *a, **kw)

    monkeypatch.setattr(departments_repo.json, "loads", counting_loads)

    repo.list_all()
    first_n = parse_calls["n"]
    repo.list_all()
    repo.list_all()
    # No additional parses while mtime is stable.
    assert parse_calls["n"] == first_n


def test_mtime_cache_invalidates_on_file_change(
    repo_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tube_scout.web.repo import departments_repo

    repo = departments_repo.DepartmentsRepo()
    repo.add(_sample_dept_dict("physiology"))
    assert {d.alias for d in repo.list_all()} == {"physiology"}

    # External rewrite (simulate operator editing departments.json) — bump mtime.
    raw = json.loads(repo_path.read_text())
    raw["departments"].append(_sample_dept_dict("nursing"))
    repo_path.write_text(json.dumps(raw))
    new_mtime = repo_path.stat().st_mtime + 1
    import os as _os

    _os.utime(repo_path, (new_mtime, new_mtime))

    aliases = {d.alias for d in repo.list_all()}
    assert aliases == {"physiology", "nursing"}
