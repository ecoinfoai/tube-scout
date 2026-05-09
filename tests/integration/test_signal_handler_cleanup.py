"""T040 RED: FR-020 — SIGINT handler must clean audio_temp + write interrupted audit + exit 130.

Phase 5 / User Story 3: The signal handler registered at collect audio/fingerprint command
start must:
1. Clean up all audio_temp/*.mp3 files (SC-004 invariant)
2. Write audit row with reason="interrupted" for the in-progress video
3. Raise SystemExit(130)

Test strategy: invoke the registered handler directly (not real SIGINT) to avoid
killing the pytest process. The handler is a module-level callable stored in
`tube_scout.cli.collect` after `collect audio/fingerprint` is invoked. We also
test the cleanup logic via a subprocess for the exit-code invariant.
"""

import csv
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


def _read_audit_rows(audit_csv: Path) -> list[dict]:
    if not audit_csv.exists():
        return []
    with audit_csv.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


# ---------------------------------------------------------------------------
# Scenario 1: signal handler cleans audio_temp/*.mp3 (SC-004)
# ---------------------------------------------------------------------------

def test_sigint_handler_cleans_audio_temp(tmp_path: Path) -> None:
    """Signal handler must remove all audio_temp/*.mp3 files (SC-004)."""
    audio_temp = tmp_path / "audio_temp"
    audio_temp.mkdir()
    mp3s = [audio_temp / f"vid{i:011d}.mp3" for i in range(3)]
    for mp3 in mp3s:
        mp3.write_bytes(b"fake audio")

    assert len(list(audio_temp.glob("*.mp3"))) == 3

    # Import the signal handler builder from collect.py
    # T042/T043 must expose a build_signal_handler(audio_temp, audit_writer, current_video_id)
    # function that returns the SIGINT/SIGTERM handler callable.
    from tube_scout.cli.collect import build_signal_handler  # type: ignore[attr-defined]

    mock_audit = MagicMock()
    handler = build_signal_handler(
        audio_temp=audio_temp,
        audit_writer=mock_audit,
        current_video_id_ref=["vid00000001"],
    )

    with pytest.raises(SystemExit) as exc_info:
        handler(2, None)  # signum=2 (SIGINT)

    assert exc_info.value.code == 130, (
        f"Expected SystemExit(130) from SIGINT handler, got {exc_info.value.code}"
    )

    remaining = list(audio_temp.glob("*.mp3"))
    assert len(remaining) == 0, (
        f"SC-004 violation: {len(remaining)} mp3(s) remain after handler: {remaining}"
    )


# ---------------------------------------------------------------------------
# Scenario 2: signal handler writes "interrupted" audit row
# ---------------------------------------------------------------------------

def test_sigint_handler_writes_interrupted_audit_row(tmp_path: Path) -> None:
    """Signal handler must append audit row with reason='interrupted' for in-progress video."""
    from tube_scout.services.audit_writer import AuditWriter
    from tube_scout.cli.collect import build_signal_handler  # type: ignore[attr-defined]

    audio_temp = tmp_path / "audio_temp"
    audio_temp.mkdir()
    project_dir = tmp_path / "project"
    project_dir.mkdir()

    audit = AuditWriter(project_dir)
    current_video_id_ref = ["in_progress_vid1"]

    handler = build_signal_handler(
        audio_temp=audio_temp,
        audit_writer=audit,
        current_video_id_ref=current_video_id_ref,
    )

    with pytest.raises(SystemExit):
        handler(2, None)

    fp_audit = project_dir / "01_collect" / "fingerprint_audit.csv"
    rows = _read_audit_rows(fp_audit)
    interrupted = [r for r in rows if r.get("reason") == "interrupted"]
    assert len(interrupted) >= 1, (
        f"Expected 'interrupted' audit row, got rows: {rows}"
    )
    assert interrupted[0]["video_id"] == "in_progress_vid1", (
        f"Wrong video_id in interrupted row: {interrupted[0]}"
    )


# ---------------------------------------------------------------------------
# Scenario 3: exit code 130 via subprocess (integration check)
# ---------------------------------------------------------------------------

def test_subprocess_sigint_exits_130(tmp_path: Path) -> None:
    """Running collect audio in subprocess and sending SIGINT must exit 130."""
    script = tmp_path / "run_collect.py"
    audio_temp = tmp_path / "audio_temp"
    audio_temp.mkdir()

    script.write_text(
        f"""
import signal, sys, time
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, "{(Path(__file__).parent.parent.parent / 'src').as_posix()}")

from tube_scout.cli.collect import build_signal_handler

audio_temp = Path("{audio_temp.as_posix()}")
# Register a dummy signal handler that exits 130 on SIGINT
handler = build_signal_handler(audio_temp=audio_temp, audit_writer=MagicMock(), current_video_id_ref=["dummy"])
signal.signal(signal.SIGINT, handler)
signal.signal(signal.SIGTERM, handler)

# Simulate mid-run work
time.sleep(10)  # Will be interrupted
""",
        encoding="utf-8",
    )

    proc = subprocess.Popen(
        [sys.executable, str(script)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    import time
    time.sleep(0.3)  # Let process start
    proc.send_signal(__import__("signal").SIGINT)
    proc.wait(timeout=5)

    assert proc.returncode == 130, (
        f"Expected exit code 130 after SIGINT, got {proc.returncode}"
    )


# ---------------------------------------------------------------------------
# Scenario 4: G-4 — SIGINT before dispatch loop starts (empty ref)
# ---------------------------------------------------------------------------

def test_sigint_before_loop_no_interrupted_row(tmp_path: Path) -> None:
    """G-4: SIGINT before dispatch loop (empty ref []) → cleanup only, no interrupted row."""
    from tube_scout.cli.collect import build_signal_handler
    from tube_scout.services.audit_writer import AuditWriter

    audio_temp = tmp_path / "audio_temp"
    audio_temp.mkdir()
    (audio_temp / "stale.mp3").write_bytes(b"data")

    project_dir = tmp_path / "project"
    project_dir.mkdir()
    audit = AuditWriter(project_dir)

    # Empty list = no video in progress yet
    current_video_id_ref: list[str] = []

    handler = build_signal_handler(
        audio_temp=audio_temp,
        audit_writer=audit,
        current_video_id_ref=current_video_id_ref,
    )

    with pytest.raises(SystemExit) as exc_info:
        handler(2, None)

    assert exc_info.value.code == 130
    # mp3 must be cleaned even if no video in progress
    assert not list(audio_temp.glob("*.mp3")), "SC-004: mp3 must be removed"
    # No interrupted row when no video was in progress
    fp_audit = project_dir / "01_collect" / "fingerprint_audit.csv"
    rows = _read_audit_rows(fp_audit)
    assert len(rows) == 0, f"Expected no audit rows when ref empty, got {rows}"


def test_sigint_ref_sentinel_not_written_as_video_id(tmp_path: Path) -> None:
    """G-4: empty ref sentinel must NOT produce a row with video_id='' or '(unknown)'."""
    from tube_scout.cli.collect import build_signal_handler
    from tube_scout.services.audit_writer import AuditWriter

    audio_temp = tmp_path / "audio_temp2"
    audio_temp.mkdir()
    project_dir = tmp_path / "project2"
    project_dir.mkdir()
    audit = AuditWriter(project_dir)

    # Empty list — nothing in flight
    handler = build_signal_handler(
        audio_temp=audio_temp,
        audit_writer=audit,
        current_video_id_ref=[],
    )

    with pytest.raises(SystemExit):
        handler(2, None)

    fp_audit = project_dir / "01_collect" / "fingerprint_audit.csv"
    rows = _read_audit_rows(fp_audit)
    bad_ids = [r for r in rows if r.get("video_id") in ("", "(unknown)", "unknown")]
    assert not bad_ids, f"Sentinel video_id written to audit: {bad_ids}"


# ---------------------------------------------------------------------------
# Scenario 5: P2 cookies_source parameter in build_signal_handler
# ---------------------------------------------------------------------------

def test_signal_handler_uses_provided_cookies_source(tmp_path: Path) -> None:
    """P2: build_signal_handler must accept cookies_source and write it to audit row."""
    from tube_scout.cli.collect import build_signal_handler
    from tube_scout.services.audit_writer import AuditWriter

    audio_temp = tmp_path / "audio_temp3"
    audio_temp.mkdir()
    project_dir = tmp_path / "project3"
    project_dir.mkdir()
    audit = AuditWriter(project_dir)

    handler = build_signal_handler(
        audio_temp=audio_temp,
        audit_writer=audit,
        current_video_id_ref=["VIDCOOKIE01"],
        cookies_source="file:/home/user/.config/cookies.txt",
    )

    with pytest.raises(SystemExit):
        handler(2, None)

    fp_audit = project_dir / "01_collect" / "fingerprint_audit.csv"
    rows = _read_audit_rows(fp_audit)
    assert rows, "Expected at least one audit row"
    assert rows[0]["cookies_source"] == "file:/home/user/.config/cookies.txt", (
        f"Expected cookies_source from caller, got '{rows[0]['cookies_source']}'"
    )
