"""T035-bis: pipeline ↔ cli helper integration RED tests.

Replaces the T035 ``pipeline.not_integrated`` stub with the real services
integration via ``cli/collect._collect_all_for_web``.

Coverage (5 cases):

1. Happy path — 5 collect stages + reuse_detection skip(absent) + reporting →
   ``done``, result_dir contains 5 expected artifacts, ``on_progress``
   callback fires per stage.
2. Spec 007 reuse_detection module absent → WARN log, stage skipped (status
   stays ``running``, transitions on to ``reporting``). Constitution II:
   silent-skip 회피 — log entry must exist.
3. OAuth expired during transcripts stage → ``failed`` + ``oauth_expired``
   error code + Korean message, no internal-path leakage in progress JSON.
4. quotaExceeded during analytics stage → ``failed`` + ``quota_exceeded``.
5. Empty video list (no matched videos) → ``completed`` + matched_video_count=0
   + result page renders no-match message (FR-007e).

R-8 architect risk: the ``_collect_all_for_web`` helper MUST accept an
``on_progress`` callback so per-stage progress updates reach the UI within
spec FR-013's 5s polling SLA.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# Helpers + fixtures
# ---------------------------------------------------------------------------

PROGRESS_STAGES = [
    "listing",
    "metadata",
    "transcripts",
    "retention",
    "analytics",
]


@pytest.fixture
def env_paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setenv("TUBE_SCOUT_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("TUBE_SCOUT_CONFIG_DIR", str(tmp_path / "cfg"))
    (tmp_path / "state").mkdir(parents=True, exist_ok=True)
    (tmp_path / "cfg").mkdir(parents=True, exist_ok=True)
    from tube_scout.web.repo import db

    db.bootstrap()
    return tmp_path


def _seed_pending_job(*, job_id: str = "20260429-100000") -> str:
    from tube_scout.web.repo import jobs_repo

    jobs_repo.JobsRepo().insert_pending(
        {
            "job_id": job_id,
            "department_alias": "physiology",
            "professor_name": "홍길동",
            "course_name": "해부생리학",
            "period_start": "2026-04-01",
            "period_end": "2026-04-28",
            "started_at": datetime.now(UTC).isoformat(),
            "created_by": "ops",
        }
    )
    return job_id


# ---------------------------------------------------------------------------
# Case 1 — happy path
# ---------------------------------------------------------------------------


async def test_happy_path_emits_5_collect_stages_and_completes(
    env_paths: Path,
) -> None:
    """The integrated pipeline emits ``listing``→``metadata``→``transcripts``→
    ``retention``→``analytics`` from the helper, then ``reuse_detection``
    (skipped) → ``reporting`` → returns result_dir."""
    from tube_scout.web.jobs import pipeline

    job_id = _seed_pending_job()
    state_dir = env_paths / "state"
    project_dir = state_dir / "projects" / job_id
    project_dir.mkdir(parents=True, exist_ok=True)

    progress_log: list[tuple[str, int, int]] = []

    def on_progress(stage: str, processed: int, total: int) -> None:
        progress_log.append((stage, processed, total))

    def fake_helper(
        *,
        department_alias: str,
        professor_name: str,
        course_name: str,
        period_start: str,
        period_end: str,
        project_dir: Path,
        on_progress: Callable[[str, int, int], None],
    ) -> dict:
        # Helper MUST emit at least one progress update per collect stage
        for idx, stage in enumerate(PROGRESS_STAGES, 1):
            on_progress(stage, idx, len(PROGRESS_STAGES))
        return {
            "matched_video_count": 5,
            "videos_meta_path": str(project_dir / "videos_meta.json"),
            "channel_id": "UCxxx",
        }

    def fake_bundle_generate(*, project_dir: Path, **_kwargs) -> dict:
        artifacts = {
            "report_v1v3_html": project_dir / "v1v3.html",
            "report_v1v3_pdf": project_dir / "v1v3.pdf",
            "report_v1v3_excel": project_dir / "v1v3.xlsx",
            "report_reuse_html": project_dir / "reuse.html",
            "report_reuse_excel": project_dir / "reuse.xlsx",
        }
        for path in artifacts.values():
            path.write_text("ok", encoding="utf-8")
        return {
            **{k: str(v) for k, v in artifacts.items()},
            "matched_video_count": 5,
            "suspicious_pair_count": 0,
            "priority_summary": {"critical": 0, "high": 0, "moderate": 0, "normal": 0},
        }

    with (
        patch.object(pipeline, "_collect_all_for_web", fake_helper),
        patch.object(pipeline, "_run_reporting_stage", fake_bundle_generate),
    ):
        result_dir = await pipeline.run(
            job_id, on_progress=on_progress, project_dir=project_dir
        )

    # Per-stage progress updates required (R-8)
    stages_seen = [s for s, _p, _t in progress_log]
    for stage in PROGRESS_STAGES:
        assert stage in stages_seen, f"missing progress for {stage}"
    assert "reporting" in stages_seen
    assert stages_seen[-1] == "done" or "done" in stages_seen

    assert Path(result_dir) == project_dir
    for fname in ["v1v3.html", "v1v3.pdf", "v1v3.xlsx", "reuse.html", "reuse.xlsx"]:
        assert (project_dir / fname).is_file()


# ---------------------------------------------------------------------------
# Case 2 — spec 007 reuse_detection absent → WARN + skip
# ---------------------------------------------------------------------------


async def test_reuse_detection_module_absent_logs_warn(
    env_paths: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """If ``services.reuse_detection`` is not importable, the pipeline MUST
    log a WARN and continue — never silently swallow the absence
    (Constitution II Fail-Fast / silent-skip avoidance)."""
    from tube_scout.web.jobs import pipeline

    job_id = _seed_pending_job(job_id="20260429-100100")
    project_dir = env_paths / "state" / "projects" / job_id
    project_dir.mkdir(parents=True, exist_ok=True)

    def fake_helper(*, on_progress, project_dir, **_kwargs) -> dict:
        for idx, stage in enumerate(PROGRESS_STAGES, 1):
            on_progress(stage, idx, len(PROGRESS_STAGES))
        return {
            "matched_video_count": 1,
            "videos_meta_path": str(project_dir / "videos_meta.json"),
            "channel_id": "UCxxx",
        }

    def fake_bundle_generate(*, project_dir: Path, **_kwargs) -> dict:
        for fname in ["v1v3.html", "v1v3.pdf", "v1v3.xlsx", "reuse.html", "reuse.xlsx"]:
            (project_dir / fname).write_text("ok", encoding="utf-8")
        return {
            "report_v1v3_html": str(project_dir / "v1v3.html"),
            "report_v1v3_pdf": str(project_dir / "v1v3.pdf"),
            "report_v1v3_excel": str(project_dir / "v1v3.xlsx"),
            "report_reuse_html": str(project_dir / "reuse.html"),
            "report_reuse_excel": str(project_dir / "reuse.xlsx"),
            "matched_video_count": 1,
            "suspicious_pair_count": 0,
            "priority_summary": {"critical": 0, "high": 0, "moderate": 0, "normal": 0},
        }

    caplog.set_level(logging.WARNING, logger="tube_scout.web.jobs.pipeline")

    with (
        patch.object(pipeline, "_collect_all_for_web", fake_helper),
        patch.object(pipeline, "_run_reporting_stage", fake_bundle_generate),
        patch.object(
            pipeline,
            "_run_reuse_detection_stage",
            side_effect=ImportError("services.reuse_detection"),
        ),
    ):
        await pipeline.run(job_id, on_progress=lambda *a: None, project_dir=project_dir)

    # WARN log MUST be present — not silent skip
    warn_messages = [r.message for r in caplog.records if r.levelno == logging.WARNING]
    assert any(
        "reuse_detection" in m
        and ("skip" in m.lower() or "absent" in m.lower() or "missing" in m.lower())
        for m in warn_messages
    ), f"expected reuse_detection WARN log, got: {warn_messages}"


# ---------------------------------------------------------------------------
# Case 3 — OAuth expired during transcripts
# ---------------------------------------------------------------------------


async def test_oauth_expired_during_transcripts_raises_pipeline_error(
    env_paths: Path,
) -> None:
    """If the cli helper raises a refresh-failure error mid-collect, the
    pipeline MUST re-raise as ``PipelineError(code="pipeline.oauth_expired")``
    so the runner records the right error code + Korean message."""
    from tube_scout.web.jobs import pipeline
    from tube_scout.web.jobs.runner import PipelineError

    job_id = _seed_pending_job(job_id="20260429-100200")
    project_dir = env_paths / "state" / "projects" / job_id
    project_dir.mkdir(parents=True, exist_ok=True)

    def failing_helper(*, on_progress, **_kwargs) -> dict:
        on_progress("listing", 1, 5)
        on_progress("metadata", 2, 5)
        on_progress("transcripts", 0, 5)
        # Helper internally maps the upstream OAuth error → PipelineError
        raise PipelineError(
            code="pipeline.oauth_expired",
            detail="refresh failed for env=TUBE_SCOUT_CLIENT_SECRET_PHYS",
        )

    with patch.object(pipeline, "_collect_all_for_web", failing_helper):
        with pytest.raises(PipelineError) as excinfo:
            await pipeline.run(
                job_id, on_progress=lambda *a: None, project_dir=project_dir
            )

    assert excinfo.value.code == "pipeline.oauth_expired"
    # detail goes to log only (route handler maps code → Korean message)


# ---------------------------------------------------------------------------
# Case 4 — quotaExceeded
# ---------------------------------------------------------------------------


async def test_quota_exceeded_during_analytics_raises_pipeline_error(
    env_paths: Path,
) -> None:
    from tube_scout.web.jobs import pipeline
    from tube_scout.web.jobs.runner import PipelineError

    job_id = _seed_pending_job(job_id="20260429-100300")
    project_dir = env_paths / "state" / "projects" / job_id
    project_dir.mkdir(parents=True, exist_ok=True)

    def failing_helper(*, on_progress, **_kwargs) -> dict:
        for idx, stage in enumerate(
            ["listing", "metadata", "transcripts", "retention"], 1
        ):
            on_progress(stage, idx, 5)
        on_progress("analytics", 0, 5)
        raise PipelineError(
            code="pipeline.quota_exceeded",
            detail="HTTP 403 quotaExceeded",
        )

    with patch.object(pipeline, "_collect_all_for_web", failing_helper):
        with pytest.raises(PipelineError) as excinfo:
            await pipeline.run(
                job_id, on_progress=lambda *a: None, project_dir=project_dir
            )

    assert excinfo.value.code == "pipeline.quota_exceeded"


# ---------------------------------------------------------------------------
# Case 5 — empty video list (no matches)
# ---------------------------------------------------------------------------


async def test_empty_video_list_completes_with_zero_matches(
    env_paths: Path,
) -> None:
    """When the listing stage filters down to zero matched videos the job
    MUST still complete (status=completed) but reporting writes no
    artifacts and ``matched_video_count`` is 0 (FR-007e)."""
    from tube_scout.web.jobs import pipeline
    from tube_scout.web.repo import results_repo

    job_id = _seed_pending_job(job_id="20260429-100400")
    project_dir = env_paths / "state" / "projects" / job_id
    project_dir.mkdir(parents=True, exist_ok=True)

    def empty_helper(*, on_progress, **_kwargs) -> dict:
        # Listing returns no matches → still emits stages, just zero counts
        for stage in PROGRESS_STAGES:
            on_progress(stage, 0, 0)
        return {
            "matched_video_count": 0,
            "videos_meta_path": None,
            "channel_id": "UCxxx",
        }

    def empty_reporting(*, project_dir: Path, **_kwargs) -> dict:
        return {
            "report_v1v3_html": None,
            "report_v1v3_pdf": None,
            "report_v1v3_excel": None,
            "report_reuse_html": None,
            "report_reuse_excel": None,
            "matched_video_count": 0,
            "suspicious_pair_count": 0,
            "priority_summary": {"critical": 0, "high": 0, "moderate": 0, "normal": 0},
        }

    with (
        patch.object(pipeline, "_collect_all_for_web", empty_helper),
        patch.object(pipeline, "_run_reporting_stage", empty_reporting),
    ):
        result_dir = await pipeline.run(
            job_id, on_progress=lambda *a: None, project_dir=project_dir
        )

    assert Path(result_dir) == project_dir
    # No artifacts on disk
    assert not (project_dir / "v1v3.html").exists()

    # AnalysisResult row written with zeros (so result page shows no-match msg)
    row = results_repo.ResultsRepo().get_result(job_id)
    assert row is not None
    assert row.matched_video_count == 0
    assert row.suspicious_pair_count == 0
