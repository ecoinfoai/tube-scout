"""7-stage analysis pipeline orchestrator — STUB (T035).

⚠ STUB: services integration is deferred to T035-bis (Phase 3-B).
Stages currently raise PipelineError(code="pipeline.not_integrated").
See specs/008-admin-web-ui/tasks.md T035-bis for the integration plan.

Why a stub now:
- The existing services/ modules are class-based (YouTubeDataService,
  TranscriptService, YouTubeAnalyticsService) and require pre-built OAuth
  clients per department alias. Wrapping them safely needs (a) per-alias
  client construction, (b) per-video iteration since transcript/retention
  are single-video methods, and (c) refactoring cli/collect.py to expose a
  Typer-free helper. That work is scoped to T035-bis.
- Until then this module preserves the runner ↔ pipeline contract so the
  rest of Phase 3-A (T036 app, T037 healthz, T019 boot integration) can
  proceed without depending on the integration.

Public surface (stable across stub → T035-bis):
- ``run(job_id, on_progress, resume_from=None)`` — async entrypoint that the
  :class:`runner.JobRunner` injects via ``pipeline_fn``. Returns the
  absolute ``result_dir`` on success.
- ``ProgressCallback`` type alias for the ``(stage, processed, total)``
  signature used by the runner.

FR-019/020 (reuse_detection review filter): the stub still calls
:func:`reviews_repo.ReviewsRepo.list_resolved_pair_ids` to keep the database
warm and detect bind issues early. The result is held in a local variable;
the actual ``excluded_pair_ids`` plumbing lands in T035-bis.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from tube_scout.web.jobs.runner import PipelineError
from tube_scout.web.repo import reviews_repo

LOGGER = logging.getLogger("tube_scout.web.jobs.pipeline")

ProgressCallback = Callable[[str, int, int], None]


_STUB_DETAIL = (
    "services integration pending — see T035-bis (Phase 3-B). "
    "Refactor cli/collect.py into a Typer-free helper, then wire each "
    "stage to YouTubeDataService / TranscriptService / "
    "YouTubeAnalyticsService / video_filter_service / reporting modules."
)


async def run(
    job_id: str,
    *,
    on_progress: ProgressCallback,
    resume_from: str | None = None,
) -> str:
    """Execute the 7-stage pipeline for ``job_id`` (STUB — raises on Stage 1).

    The runner contract (see T034) calls ``on_progress(stage, processed,
    total)`` whenever a stage transitions or progress ticks. The stub:

    1. Touches :func:`reviews_repo.ReviewsRepo.list_resolved_pair_ids` so a
       broken database bind surfaces immediately rather than at T035-bis
       integration.
    2. Calls ``on_progress("listing", 0, 0)`` to mark the first transition.
    3. Raises :class:`PipelineError` with code ``pipeline.not_integrated``
       — the runner translates this to a ``failed`` row with the matching
       Korean error_message_kr (see ``errors.py``).

    Args:
        job_id: New job identifier.
        on_progress: Callback ``(stage, processed, total)``.
        resume_from: Optional original ``job_id`` for checkpoint resume.

    Returns:
        Absolute ``result_dir`` (never reached in stub form).

    Raises:
        ValueError: If ``job_id`` is empty (Constitution II Fail-Fast).
        PipelineError: Always, with code ``pipeline.not_integrated``, until
            T035-bis lands.
    """
    if not job_id:
        raise ValueError("job_id must be a non-empty string")

    # Touch the reviews repo so a broken database bind surfaces here rather
    # than at T035-bis integration. The list is intentionally unused — the
    # filter plumbing lands in T035-bis.
    _resolved_pair_ids = reviews_repo.ReviewsRepo().list_resolved_pair_ids()
    LOGGER.debug(
        "T035 stub: reviews_repo bound (resolved=%d) — resume_from=%s",
        len(_resolved_pair_ids),
        resume_from,
    )

    # Announce the first stage transition so the UI shows '영상 목록 수집 중'
    # before the stub raises.
    on_progress("listing", 0, 0)

    LOGGER.warning(
        "T035 stub invoked for job %s — pipeline.not_integrated will be "
        "raised. See T035-bis.",
        job_id,
    )
    raise PipelineError(code="pipeline.not_integrated", detail=_STUB_DETAIL)
