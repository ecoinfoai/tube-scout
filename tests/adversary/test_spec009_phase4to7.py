"""Adversary tests for spec 009 Phase 4-7 (US2/US3/US4 + amendment + carry-over).

Findings landed by adversary sweep on 2026-05-07. Each test below codifies a
specific weakness discovered while attacking the in-flight implementation. Tests
that currently DEMONSTRATE a defect are marked with ``xfail(strict=True)`` so a
future fix flips them to XPASS, prompting the adversary marker to be removed.
Tests that codify present behavior (no fix expected) pass as-is.
"""

from __future__ import annotations

import io
import json
import os
import shutil
import tempfile
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Phase 4 — User Story 2 (project resolution)
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=True,
    reason=(
        "P1 — resolve_project raises bare typer.Exit instead of LatestProjectMissing"
        " (errors.py:133). cli/errors.py defines the class but cli/project.py:35 "
        "never raises it; operators see a silent exit code 1 with no next_command."
    ),
)
def test_p1_empty_project_dir_raises_latest_project_missing(tmp_path: Path) -> None:
    """``--project latest`` with no projects/ dir must raise LatestProjectMissing."""
    from tube_scout.cli.errors import LatestProjectMissing
    from tube_scout.cli.project import resolve_project

    nonexistent = str(tmp_path / "projects")
    with pytest.raises(LatestProjectMissing):
        resolve_project(nonexistent, "latest")


@pytest.mark.xfail(
    strict=True,
    reason=(
        "P2 — ProjectManager.resolve_latest_strict (manager.py:254) follows "
        "arbitrary symlinks via Path.resolve() with no containment check. An "
        "attacker who can write ``projects/latest`` (relative symlink) can "
        "redirect every consumer command to /tmp/evil. Add a "
        "resolve().is_relative_to(self._root.resolve()) guard."
    ),
)
def test_p2_symlink_poisoning_rejected_by_resolve_latest_strict(
    tmp_path: Path,
) -> None:
    """resolve_latest_strict MUST reject symlinks that escape projects_root."""
    from tube_scout.output.manager import ProjectManager

    root = tmp_path / "projects"
    root.mkdir()
    real = root / "20260507-100000"
    (real / "01_collect").mkdir(parents=True)
    (real / "01_collect" / "data.json").write_text("{}")

    attacker = tmp_path / "evil"
    (attacker / "01_collect").mkdir(parents=True)
    (attacker / "01_collect" / "fake.json").write_text("{}")

    latest = root / "latest"
    os.symlink("../evil", latest)

    mgr = ProjectManager(projects_root=root)
    with pytest.raises(Exception, match=r"(?i)outside|escape|containment"):
        mgr.resolve_latest_strict()


def test_p4_producer_crash_leaves_empty_sibling_dir(tmp_path: Path) -> None:
    """create_project leaks an empty sibling dir on producer crash before commit_latest.

    BY DESIGN: latest is not advanced (correct). Empty sibling dir is operator
    cleanup territory. This test is informational — captures the leak so operators
    are not surprised.
    """
    from tube_scout.output.manager import ProjectManager

    root = tmp_path / "projects"
    mgr = ProjectManager(projects_root=root)
    new_proj = mgr.create_project()
    # Simulate process crash before any artifact write.
    assert new_proj.exists()
    assert not (root / "latest").exists()
    siblings = list(root.iterdir())
    # Confirms: leaked empty dir survives crash. Document operator pattern:
    # `tube-scout admin gc-projects` should reap empty siblings.
    assert len(siblings) == 1
    assert siblings[0] == new_proj


def test_p3_commit_latest_tmp_link_collision_under_clock_skew(tmp_path: Path) -> None:
    """tmp_link uses pid+HMS%f. Two threads in same pid CAN collide on microsecond.

    Demonstrates the theoretical race window. The unlink-then-symlink_to+os.replace
    sequence is the actual atomic primitive — but if two threads in the same pid
    hit the exact same %f, both will try to ``unlink`` the same tmp_link,
    causing one to ``FileNotFoundError`` from unlink (mitigated by the
    is_symlink check) but THEN the second ``symlink_to`` may fire on a
    half-unlinked path. In practice the per-microsecond resolution makes this
    hard to hit, but the persona stands as a race-window note.
    """
    from tube_scout.output.manager import ProjectManager

    root = tmp_path / "projects"
    root.mkdir()
    p1 = root / "20260507-100000"
    p2 = root / "20260507-100001"
    for p in (p1, p2):
        (p / "01_collect").mkdir(parents=True)
        (p / "01_collect" / "data.json").write_text("{}")

    mgr1 = ProjectManager(projects_root=root)
    mgr1.open_project(p1)
    mgr1.commit_latest()
    mgr2 = ProjectManager(projects_root=root)
    mgr2.open_project(p2)
    mgr2.commit_latest()
    # Final state: latest -> p2 (last-writer-wins, atomic POSIX rename).
    assert (root / "latest").resolve() == p2.resolve()


# ---------------------------------------------------------------------------
# Phase 5 — User Story 3 (symmetric --channel)
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=True,
    reason=(
        "P11 — collect_all_command (cli/collect.py:806) does NOT pass --channel "
        "to the comments or transcripts sub-stages. transcripts has its own "
        "--channel option but composite never forwards it. Bypasses FR-006."
    ),
)
def test_p11_collect_all_propagates_channel_to_every_stage(tmp_path: Path) -> None:
    """collect_all_command must pass --channel to every sub-stage."""
    import inspect

    from tube_scout.cli.collect import collect_all_command

    src = inspect.getsource(collect_all_command)
    # Each elif block for a stage that has a --channel option must include
    # `kwargs["channel"] = channel`.
    for stage_name in ("comments", "transcripts"):
        block = src.split(f'stage_name == "{stage_name}"')[1].split("elif stage_name")[0]
        assert 'kwargs["channel"] = channel' in block, (
            f"Stage {stage_name!r} does not propagate --channel from collect_all_command"
        )


def test_p9_stale_alias_token_deleted_out_of_band(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Registry has alias N but token file deleted out-of-band.

    Current behavior: authenticate_channel raises raw ``FileNotFoundError``
    (auth.py:405). The CLI catches it via ``except (FileNotFoundError, ValueError)``
    and prints ``str(e)`` with no ``next_command`` — bypasses UserFacingError
    contract (Constitution II Fail-Fast hint).

    SUGGESTED FIX: raise UserFacingError with next_command =
    ``tube-scout auth --channel <alias>``.
    """
    tokens_dir = tmp_path / "tokens"
    tokens_dir.mkdir()
    monkeypatch.setenv("TUBE_SCOUT_TOKENS_DIR", str(tokens_dir))

    token_file = tokens_dir / "nursing.json"  # NOT created
    registry = {
        "nursing": {
            "alias": "nursing",
            "channel_id": "UC" + "A" * 22,
            "channel_name": "nursing",
            "registered_at": "2026-05-07T00:00:00",
            "last_used_at": "2026-05-07T00:00:00",
            "token_path": str(token_file),
        }
    }
    (tokens_dir / "channels.json").write_text(json.dumps(registry))

    from tube_scout.services import auth_migration
    from tube_scout.services.auth import authenticate_channel

    auth_migration.reset_for_testing()
    monkeypatch.setattr(auth_migration, "run_once", lambda **_kw: None)

    with pytest.raises(FileNotFoundError, match="Token file not found"):
        authenticate_channel("nursing")


# ---------------------------------------------------------------------------
# Phase 7 amendment — device-flow / browser-redirect 401 fallback
# ---------------------------------------------------------------------------


def test_p17_browser_redirect_swallows_all_oauth_errors_into_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """run_browser_redirect_with_timeout maps every OAuth exception to BrowserRedirectTimeout.

    Operators observing this error cannot tell whether the cause was:
      - genuine timeout
      - invalid_client (mis-configured client secret)
      - access_denied (user clicked deny)
      - network error
      - corrupted client_secret JSON

    Constitution II silent-skip: ``except Exception: creds = None`` (auth_cli.py:92)
    swallows the diagnostic. SUGGESTED FIX: separate Exception classes per
    error category, preserve __cause__ chain.
    """
    from google_auth_oauthlib.flow import InstalledAppFlow

    from tube_scout.cli.auth_cli import (
        BrowserRedirectTimeout,
        run_browser_redirect_with_timeout,
    )

    class _BoomFlow:
        def run_local_server(self, *_a, **_k):
            raise RuntimeError("invalid_client (401) — should NOT collapse to timeout")

    def _from_secrets(*_a, **_k):
        return _BoomFlow()

    monkeypatch.setattr(
        InstalledAppFlow,
        "from_client_secrets_file",
        classmethod(lambda cls, *a, **k: _from_secrets()),
    )
    monkeypatch.setattr(
        "tube_scout.services.auth._default_client_secret_path",
        lambda: tmp_path / "fake.json",
    )

    with pytest.raises(BrowserRedirectTimeout):
        run_browser_redirect_with_timeout(alias="nursing", timeout_seconds=0.1)
    # ^ The PASS demonstrates the bug — RuntimeError got laundered into
    # BrowserRedirectTimeout. There is no way for an operator to recover the
    # underlying invalid_client signal. Once the fallback amendment lands, the
    # test should assert a more specific error class (or that __cause__ chains).


# ---------------------------------------------------------------------------
# Carry-over — legacy migration error rendering, registry validation
# ---------------------------------------------------------------------------


def test_p18_legacy_token_corrupt_renders_full_path_with_pii() -> None:
    """LegacyTokenCorrupt.message embeds the full filesystem path.

    Path includes operator username (e.g. ``/home/operator/.config/tube-scout/...``).
    For shared-screen demos, support tickets, and crash logs sent to vendors
    this is PII leakage. SUGGESTED FIX: redact home-dir prefix, render a
    relative path or token basename only.

    ALSO: this class is currently UNUSED — auth_migration.py:158 writes the
    corrupt-token notice via ``sys.stderr.write`` and ``unlink`` rather than
    raising LegacyTokenCorrupt. Carry-over D-13/D-14 wiring still pending.
    """
    from tube_scout.cli.errors import LegacyTokenCorrupt, render_error

    e = LegacyTokenCorrupt(
        token_path="/home/operator/.config/tube-scout/token.json",
        reason="not JSON",
    )
    buf = io.StringIO()
    render_error(e, buf)
    rendered = buf.getvalue()
    assert "/home/operator" in rendered, (
        "Demonstrates PII leak: full username path surfaces in operator output."
    )


@pytest.mark.xfail(
    strict=True,
    reason=(
        "P19 — auth_migration._atomic_replace (line 98) and _process_legacy_path "
        "(line 154) call .read_bytes() on the legacy path. If a malicious actor "
        "places a symlink to /dev/zero (or /dev/random) at the legacy token path, "
        "the migration consumes unbounded memory. SUGGESTED FIX: stat-and-cap, "
        "reject non-regular files, or use os.O_NOFOLLOW + size_limit."
    ),
)
def test_p19_legacy_token_dev_zero_symlink_bounded(tmp_path: Path) -> None:
    """Legacy token symlinked to /dev/zero must be rejected, not consumed."""
    from tube_scout.services.auth_migration import _process_legacy_path

    legacy = tmp_path / "token.json"
    os.symlink("/dev/zero", legacy)

    cache = tmp_path / "cache.json"
    config_dir = tmp_path

    finished = threading.Event()
    err: list[BaseException] = []

    def _go() -> None:
        try:
            _process_legacy_path(legacy, config_dir=config_dir, cache_path=cache)
        except BaseException as exc:  # noqa: BLE001 — we want EVERY exit reason
            err.append(exc)
        finally:
            finished.set()

    t = threading.Thread(target=_go, daemon=True)
    t.start()
    completed = finished.wait(timeout=2.0)
    if not completed:
        pytest.fail(
            "_process_legacy_path hung on /dev/zero symlink — read_bytes() "
            "consumed memory until killed externally."
        )
    assert err, "Expected an explicit rejection, not silent success"


# ---------------------------------------------------------------------------
# Phase 6 (US4) — pre-emptive guidance (transcripts_audit not yet implemented)
# ---------------------------------------------------------------------------


def test_p12_csv_injection_in_transcripts_audit_skipped() -> None:
    """When transcripts_audit module lands, every CSV cell that begins with
    ``=``, ``+``, ``-``, ``@``, or contains a literal newline / quote MUST be
    quoted-and-escaped per Excel CSV injection guidance (OWASP).

    Persona is filed pre-emptively: writing this test before the module exists
    forces the developer to consider injection vectors during T039 GREEN.
    """
    pytest.skip(
        "transcripts_audit not yet implemented — adversary placeholder for T039."
    )


def test_p13_massive_audit_row_count_streamed_skipped() -> None:
    """write_audit_csv with 10k rows should stream, not buffer in-memory.

    polars / csv.writer should be the implementation, not an f-string join.
    """
    pytest.skip(
        "transcripts_audit not yet implemented — adversary placeholder for T039."
    )


def test_p14_classify_miss_with_none_errors_skipped() -> None:
    """classify_miss(primary_error=None, fallback_error=None, video_meta) must
    not raise AttributeError on .__class__.__name__ access. Use isinstance
    or explicit None-handling.
    """
    pytest.skip(
        "transcripts_audit not yet implemented — adversary placeholder for T039."
    )


def test_p15_source_field_forgery_skipped() -> None:
    """If a cached transcript JSON sets ``source: captions_api`` but the file
    is on a public-scrape code path, downstream consumers must not trust the
    field. Source must be derived at write-time, not read-from-disk.
    """
    pytest.skip(
        "transcripts_audit not yet implemented — adversary placeholder for T038."
    )
