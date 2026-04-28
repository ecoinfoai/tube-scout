"""7-stage analysis pipeline orchestrator (T035).

Orchestrator (RULE4): drives the existing CLI services in order without
introducing any analysis logic of its own (Constitution IV CLI-First). Each
stage emits an ``on_progress(stage, processed, total)`` call so the runner
can update the SQLite state and the browser polling loop reflects forward
movement.

Stages (per spec FR-009 + data-model.md JobStage):
1. listing — services.youtube_data.list_videos
2. metadata — services.youtube_data.fetch_metadata
3. transcripts — services.transcript.collect
4. retention — services.youtube_analytics.fetch_retention
5. analytics — services.youtube_analytics.fetch_analytics
6. reuse_detection — spec 007 reuse_detection.scan, with
   reviews_repo.list_resolved_pair_ids() filter (FR-020 enforce)
7. reporting — services.video_filter_service.generate_reports

Failure mapping → :class:`runner.PipelineError`:
- HTTP 401 / RefreshError → ``pipeline.oauth_expired``
- HTTP 403 quotaExceeded → ``pipeline.quota_exceeded``
- empty video list → ``pipeline.no_videos``
- everything else → ``pipeline.internal``

Note: We import services lazily so unit tests can stub them and so an
upstream service module that fails to import (e.g. spec 007 not yet
shipped on a given branch) raises a typed PipelineError rather than
breaking the entire web app.
"""

from __future__ import annotations

import asyncio
import importlib
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from tube_scout.web.jobs.runner import PipelineError
from tube_scout.web.repo import reviews_repo

LOGGER = logging.getLogger("tube_scout.web.jobs.pipeline")

ProgressCallback = Callable[[str, int, int], None]


def _load(module: str) -> Any:
    """Import ``module`` lazily; convert ImportError to PipelineError.

    Args:
        module: Fully-qualified module name (e.g. ``services.youtube_data``).

    Returns:
        The imported module object.

    Raises:
        PipelineError: with code ``pipeline.internal`` if the module is missing.
    """
    try:
        return importlib.import_module(f"tube_scout.{module}")
    except ImportError as exc:
        raise PipelineError(
            code="pipeline.internal",
            detail=f"required service module missing: tube_scout.{module}: {exc}",
        ) from exc


def _stage(
    on_progress: ProgressCallback,
    stage: str,
) -> None:
    """Reset progress counters at the start of a new stage."""
    on_progress(stage, 0, 0)


async def _run_in_thread(fn, *args, **kwargs) -> Any:
    """Run a synchronous service function on the default thread pool.

    Wraps :func:`asyncio.to_thread` so blocking I/O (Google APIs, file
    writes) does not stall the event loop (architect ADR R-2).
    """
    return await asyncio.to_thread(fn, *args, **kwargs)


async def run(
    job_id: str,
    *,
    on_progress: ProgressCallback,
    resume_from: str | None = None,
) -> str:
    """Execute the 7-stage pipeline for ``job_id``.

    Args:
        job_id: New job identifier.
        on_progress: Callback ``(stage, processed, total)`` invoked once per
            stage entry (counts reset to 0,0) and once per progress tick.
        resume_from: Optional original ``job_id`` whose checkpoint should
            be resumed (T073 retry route).

    Returns:
        Absolute ``result_dir`` path under ``projects/{job_id}/``.

    Raises:
        PipelineError: With one of the codes mapped above.
    """
    if not job_id:
        raise ValueError("job_id must be a non-empty string")
    youtube_data = _load("services.youtube_data")
    transcript = _load("services.transcript")
    youtube_analytics = _load("services.youtube_analytics")
    video_filter = _load("services.video_filter_service")
    reuse_detection = _load_optional("services.reuse_detection")

    # Stage 1: listing
    _stage(on_progress, "listing")
    try:
        video_ids = await _run_in_thread(
            youtube_data.list_videos, job_id, resume_from=resume_from
        )
    except Exception as exc:  # noqa: BLE001 — translate to PipelineError below
        raise _translate_failure(exc) from exc
    if not video_ids:
        raise PipelineError(
            code="pipeline.no_videos",
            detail="list_videos returned empty result set",
        )
    on_progress("listing", len(video_ids), len(video_ids))

    # Stage 2: metadata
    _stage(on_progress, "metadata")
    try:
        await _run_in_thread(youtube_data.fetch_metadata, job_id, video_ids)
    except Exception as exc:  # noqa: BLE001
        raise _translate_failure(exc) from exc
    on_progress("metadata", len(video_ids), len(video_ids))

    # Stage 3: transcripts
    _stage(on_progress, "transcripts")
    try:
        await _run_in_thread(transcript.collect, job_id, video_ids)
    except Exception as exc:  # noqa: BLE001
        raise _translate_failure(exc) from exc
    on_progress("transcripts", len(video_ids), len(video_ids))

    # Stage 4: retention
    _stage(on_progress, "retention")
    try:
        await _run_in_thread(youtube_analytics.fetch_retention, job_id, video_ids)
    except Exception as exc:  # noqa: BLE001
        raise _translate_failure(exc) from exc
    on_progress("retention", len(video_ids), len(video_ids))

    # Stage 5: analytics
    _stage(on_progress, "analytics")
    try:
        await _run_in_thread(youtube_analytics.fetch_analytics, job_id, video_ids)
    except Exception as exc:  # noqa: BLE001
        raise _translate_failure(exc) from exc
    on_progress("analytics", len(video_ids), len(video_ids))

    # Stage 6: reuse_detection — filtered by previously resolved pairs (FR-020)
    _stage(on_progress, "reuse_detection")
    if reuse_detection is not None:
        resolved_pair_ids = reviews_repo.ReviewsRepo().list_resolved_pair_ids()
        try:
            await _run_in_thread(
                reuse_detection.scan,
                job_id,
                video_ids,
                excluded_pair_ids=resolved_pair_ids,
            )
        except Exception as exc:  # noqa: BLE001
            raise _translate_failure(exc) from exc
    else:
        # spec 007 module not yet shipped — pipeline degrades gracefully but
        # records the gap so the auditor can flag missing FR-019/020 coverage.
        LOGGER.warning(
            "reuse_detection module unavailable for job %s — skipping stage; "
            "FR-019/020 not enforced",
            job_id,
        )
    on_progress("reuse_detection", len(video_ids), len(video_ids))

    # Stage 7: reporting
    _stage(on_progress, "reporting")
    try:
        result_dir: Path = await _run_in_thread(
            video_filter.generate_reports, job_id, video_ids
        )
    except Exception as exc:  # noqa: BLE001
        raise _translate_failure(exc) from exc
    on_progress("reporting", len(video_ids), len(video_ids))
    on_progress("done", len(video_ids), len(video_ids))
    return str(result_dir)


def _load_optional(module: str) -> Any | None:
    """Return the module or None when missing (used for spec 007)."""
    try:
        return importlib.import_module(f"tube_scout.{module}")
    except ImportError:
        return None


def _translate_failure(exc: Exception) -> PipelineError:
    """Map a service-layer exception to the appropriate PipelineError code."""
    text = str(exc).lower()
    name = type(exc).__name__
    if name in {"RefreshError"} or "401" in text or "invalid_grant" in text:
        return PipelineError(code="pipeline.oauth_expired", detail=str(exc))
    if "quotaexceeded" in text or "quota_exceeded" in text or "403" in text:
        return PipelineError(code="pipeline.quota_exceeded", detail=str(exc))
    return PipelineError(code="pipeline.internal", detail=f"{name}: {exc}")
