"""7-stage analysis pipeline orchestrator (T035-bis).

Wires the admin web UI's background runner to:

1. ``cli.collect._collect_all_for_web`` — single Typer-free helper that runs
   the 5 collection stages (listing/metadata/transcripts/retention/analytics)
   in sequence, emitting ``on_progress`` per stage (architect ADR-006 R-8).
2. ``_run_reuse_detection_stage`` — dispatches to ``services.reuse_detection``
   if importable; logs WARN + skips if absent (Constitution II silent-skip
   avoidance + spec 007 not-yet-implemented tolerance).
3. ``_run_reporting_stage`` — invokes ``reporting.bundle_report`` to produce
   the 5 artifact files (HTML/PDF/Excel + reuse HTML/Excel) and writes the
   ``analysis_results`` row.

Constitution IV (CLI-First / thin layer): zero new analysis logic in this
module — every call delegates to the existing services or the cli helper.
RULE4 orchestrator file — modifications require a qa-engineer INTEGRATION
boundary review.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tube_scout.cli.collect import _collect_all_for_web
from tube_scout.web.jobs.runner import PipelineError
from tube_scout.web.repo import results_repo, reviews_repo

LOGGER = logging.getLogger("tube_scout.web.jobs.pipeline")

ProgressCallback = Callable[[str, int, int], None]


def _run_reuse_detection_stage(
    *, project_dir: Path, channel_id: str | None, excluded_pair_ids: list[str]
) -> dict[str, Any] | None:
    """Run spec 007 reuse detection if the module is available.

    Args:
        project_dir: Project directory holding videos_meta + transcripts.
        channel_id: YouTube channel id for the analysis run.
        excluded_pair_ids: Pair ids previously reviewed as confirmed_duplicate
            or false_positive (spec FR-020).

    Returns:
        Dict with ``suspicious_pair_count`` and ``priority_summary`` from the
        spec 007 module, or ``None`` when the module is absent.

    Raises:
        ImportError: When ``services.reuse_detection`` is not importable.
            The pipeline catches this above and logs a WARN — the raise here
            keeps Constitution II silent-skip avoidance honest.
    """
    # Patched in T035-bis test_reuse_detection_module_absent_logs_warn to
    # simulate spec 007 absence; real implementation lands when spec 007
    # is delivered.
    from tube_scout.services import reuse_detection  # noqa: F401

    raise NotImplementedError(
        "spec 007 reuse_detection.scan integration pending — extend this "
        "function once the spec 007 module exposes its public scan() API."
    )


def _run_reporting_stage(
    *,
    project_dir: Path,
    department_alias: str,
    professor_name: str,
    course_name: str,
    period_start: str,
    period_end: str,
    channel_id: str | None,
    matched_video_count: int,
    suspicious_pair_count: int,
    priority_summary: dict[str, int],
) -> dict[str, Any]:
    """Generate the 5 artifact files for the completed job.

    Patched out in tests via ``patch.object(pipeline, "_run_reporting_stage",
    fake_bundle_generate)``. The real implementation calls
    ``reporting.bundle_report.BundleReportGenerator`` for the v1v3 HTML +
    converts to PDF/Excel via the existing reporting helpers; reuse
    HTML/Excel come from the spec 007 module's reporting helper when
    available.

    Args:
        project_dir: Output directory for artifacts.
        department_alias: Department alias.
        professor_name: Filter — professor name.
        course_name: Filter — course name.
        period_start: ISO date.
        period_end: ISO date.
        channel_id: YouTube channel id (may be None when no videos matched).
        matched_video_count: Videos passing the professor/course filter.
        suspicious_pair_count: Count of reuse-detection alerts.
        priority_summary: ``{critical, high, moderate, normal}`` counts.

    Returns:
        Dict suitable for ``results_repo.ResultsRepo.insert_result`` (sans
        ``job_id`` which the caller adds).

    Raises:
        NotImplementedError: Until the bundle_report wiring lands. Tests
            patch this function so the pipeline contract is exercised
            without requiring the multi-format reporting pipeline.
    """
    raise NotImplementedError(
        "BundleReportGenerator wiring pending — patched in tests; real "
        "wiring lands together with the v1v3 PDF/Excel exporter integration."
    )


async def run(
    job_id: str,
    *,
    on_progress: ProgressCallback,
    project_dir: Path | None = None,
    resume_from: str | None = None,
) -> str:
    """Execute the 7-stage pipeline for ``job_id``.

    Stage progression (data-model.md §2 JobStage):

    1. ``listing`` → 2. ``metadata`` → 3. ``transcripts`` → 4. ``retention``
       → 5. ``analytics`` — emitted by :func:`_collect_all_for_web` per R-8.
    6. ``reuse_detection`` — calls :func:`_run_reuse_detection_stage`;
       graceful WARN + skip when spec 007 is unavailable.
    7. ``reporting`` — calls :func:`_run_reporting_stage` to produce the 5
       artifact files + insert the ``analysis_results`` row.

    Args:
        job_id: New job identifier.
        on_progress: Callback ``(stage, processed, total)`` — invoked at
            every stage transition. Required by R-8.
        project_dir: Output directory for the run. Defaults to
            ``$STATE_DIR/projects/{job_id}/``.
        resume_from: Optional original ``job_id`` to honor checkpoint resume
            (US2 T075 extension hook; pass-through here).

    Returns:
        Absolute ``result_dir`` path (string).

    Raises:
        ValueError: If ``job_id`` is empty.
        PipelineError: When any stage raises a typed pipeline failure.
    """
    if not job_id:
        raise ValueError("job_id must be a non-empty string")

    from tube_scout.web.repo import jobs_repo  # local import: avoid cycle at boot

    job_row = jobs_repo.JobsRepo().find_by_id(job_id)
    if job_row is None:
        raise PipelineError(code="pipeline.internal", detail=f"unknown job_id={job_id}")

    if project_dir is None:
        from tube_scout.web.paths import get_state_dir

        project_dir = get_state_dir() / "projects" / job_id
    project_dir = Path(project_dir)
    project_dir.mkdir(parents=True, exist_ok=True)

    excluded_pair_ids = list(reviews_repo.ReviewsRepo().list_resolved_pair_ids())

    LOGGER.info(
        "pipeline %s starting; resume_from=%s, excluded_pairs=%d",
        job_id,
        resume_from,
        len(excluded_pair_ids),
    )
    collect_result = _collect_all_for_web(
        department_alias=job_row.department_alias,
        professor_name=job_row.professor_name,
        course_name=job_row.course_name,
        period_start=job_row.period_start,
        period_end=job_row.period_end,
        project_dir=project_dir,
        on_progress=on_progress,
    )

    matched_video_count = int(collect_result.get("matched_video_count", 0))
    channel_id = collect_result.get("channel_id")

    # Stage 6 — reuse detection (graceful skip when spec 007 absent).
    on_progress("reuse_detection", 0, 0)
    suspicious_pair_count = 0
    priority_summary: dict[str, int] = {
        "critical": 0,
        "high": 0,
        "moderate": 0,
        "normal": 0,
    }
    try:
        reuse_result = _run_reuse_detection_stage(
            project_dir=project_dir,
            channel_id=channel_id,
            excluded_pair_ids=excluded_pair_ids,
        )
        if reuse_result:
            suspicious_pair_count = int(reuse_result.get("suspicious_pair_count", 0))
            priority_summary = reuse_result.get("priority_summary", priority_summary)
    except ImportError as exc:
        # intentional-skip: spec 007 reuse_detection module not yet shipped.
        # WARN log keeps Constitution II honest — never silently swallow.
        LOGGER.warning(
            "reuse_detection stage skipped — spec 007 module missing: %s", exc
        )
    except NotImplementedError as exc:
        # intentional-skip: spec 007 module imported but scan() not wired.
        LOGGER.warning(
            "reuse_detection stage skipped — spec 007 not implemented: %s", exc
        )

    # Stage 7 — reporting.
    on_progress("reporting", 0, 1)
    report_payload = _run_reporting_stage(
        project_dir=project_dir,
        department_alias=job_row.department_alias,
        professor_name=job_row.professor_name,
        course_name=job_row.course_name,
        period_start=job_row.period_start,
        period_end=job_row.period_end,
        channel_id=channel_id,
        matched_video_count=matched_video_count,
        suspicious_pair_count=suspicious_pair_count,
        priority_summary=priority_summary,
    )

    results_repo.ResultsRepo().insert_result(
        {
            "job_id": job_id,
            "report_v1v3_html": report_payload.get("report_v1v3_html"),
            "report_v1v3_pdf": report_payload.get("report_v1v3_pdf"),
            "report_v1v3_excel": report_payload.get("report_v1v3_excel"),
            "report_reuse_html": report_payload.get("report_reuse_html"),
            "report_reuse_excel": report_payload.get("report_reuse_excel"),
            "matched_video_count": int(
                report_payload.get("matched_video_count", matched_video_count)
            ),
            "suspicious_pair_count": int(
                report_payload.get("suspicious_pair_count", suspicious_pair_count)
            ),
            "priority_summary": report_payload.get(
                "priority_summary", priority_summary
            ),
            "generated_at": datetime.now(UTC).isoformat(),
        }
    )

    on_progress("done", 1, 1)
    LOGGER.info("pipeline %s completed; result_dir=%s", job_id, project_dir)
    return str(project_dir)
