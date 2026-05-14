"""Spec 013 SC-002 — wall-clock measurement for 200-video M-nC2 analysis.

This test is env-gated by ``TUBE_SCOUT_PERF_FIXTURE_200_VIDEO``. The
environment variable MUST point at a v4 ContentDB file pre-populated
with a 200-video professor pool (channel_metadata + video_metadata +
processing_status rows). The operator builds this fixture once on the
production GPU server (see _workspace/measurement/nc2_runtime_phase3.md
for the recipe).

When the env var is absent the test ``pytest.skip``s — CI and laptop
runs do not need the fixture. The test file must still import-clean so
collection works everywhere.

Outputs a measurement record to
``_workspace/measurement/nc2_runtime_phase3.md`` (appended). SC-002
evidence for spec 013 Phase 6 sign-off.

Mark: ``@pytest.mark.slow``.
"""

from __future__ import annotations

import os
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

PERF_FIXTURE_ENV = "TUBE_SCOUT_PERF_FIXTURE_200_VIDEO"
PROFESSOR_ENV = "TUBE_SCOUT_PERF_PROFESSOR"
CHANNEL_ALIAS_ENV = "TUBE_SCOUT_PERF_CHANNEL_ALIAS"
MEASUREMENT_OUT = (
    Path(__file__).resolve().parents[2]
    / "_workspace"
    / "measurement"
    / "nc2_runtime_phase3.md"
)


def _resolve_fixture_path() -> Path:
    raw = os.environ.get(PERF_FIXTURE_ENV)
    if not raw:
        pytest.skip(
            f"{PERF_FIXTURE_ENV} unset — production GPU fixture required for SC-002"
        )
    path = Path(raw).expanduser().resolve()
    if not path.exists():
        pytest.fail(
            f"{PERF_FIXTURE_ENV}={raw!r} does not exist; "
            "build the 200-video v4 fixture before running this perf test."
        )
    return path


def _append_measurement(record: str) -> None:
    MEASUREMENT_OUT.parent.mkdir(parents=True, exist_ok=True)
    header_needed = not MEASUREMENT_OUT.exists()
    with MEASUREMENT_OUT.open("a", encoding="utf-8") as fh:
        if header_needed:
            fh.write(
                "# spec 013 SC-002 — 200-video M-nC2 wall-clock measurements\n\n"
                "Each entry is appended by `tests/perf/test_nc2_runtime.py`.\n\n"
                "| timestamp_utc | fixture | professor | channel_alias | "
                "pairs_generated | pairs_analyzed | elapsed_seconds | "
                "matching_mode |\n"
                "|---|---|---|---|---|---|---|---|\n"
            )
        fh.write(record)


@pytest.mark.slow
def test_sc002_nc2_200_video_wall_clock(tmp_path: Path) -> None:
    """Measure wall-clock for run_nc2_analysis on a 200-video pool.

    Skips unless ``TUBE_SCOUT_PERF_FIXTURE_200_VIDEO`` points at a v4
    ContentDB. Does NOT assert a budget — the budget is set in the spec
    follow-up after Phase 1/2 measurements (SC-002 wording). The measured
    wall-clock is appended to ``_workspace/measurement/nc2_runtime_phase3.md``
    so the spec maintainer can commit a budget after observing enough
    runs.
    """
    fixture_db = _resolve_fixture_path()
    professor = os.environ.get(PROFESSOR_ENV, "prof-perf-200")
    channel_alias = os.environ.get(CHANNEL_ALIAS_ENV, "ch-test")

    from tube_scout.services.nc2_matcher import run_nc2_analysis
    from tube_scout.storage.content_db import ContentDB, _ensure_v4

    _ensure_v4(fixture_db)
    db = ContentDB(fixture_db)

    start = time.monotonic()
    result = run_nc2_analysis(
        professor=professor,
        channel_alias=channel_alias,
        db=db,
        matching_mode="M-nC2",
        layer_a_min_seconds=30.0,
        resume=False,
        force=True,
    )
    elapsed = time.monotonic() - start

    timestamp = datetime.now(UTC).isoformat(timespec="seconds")
    record = (
        f"| {timestamp} | {fixture_db} | {professor} | {channel_alias} | "
        f"{result.total_pairs_generated} | {result.pairs_analyzed} | "
        f"{elapsed:.2f} | M-nC2 |\n"
    )
    _append_measurement(record)

    assert result.total_pairs_generated > 0, (
        "fixture must yield at least one nC2 pair after Layer A cull"
    )
    assert elapsed > 0.0
