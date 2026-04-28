"""Background job runner — asyncio Task + per-department flock (T034).

Orchestrator (RULE4): spawns asyncio tasks for new analysis jobs, holds an
exclusive ``fcntl.flock`` per department alias so duplicate submissions are
rejected at the OS level (architect ADR R-7), and updates the
``analysis_jobs`` table through :class:`jobs_repo.JobsRepo` as the pipeline
progresses.

Lifecycle hooks (per spec FR-022, FR-022a):
- start_job(): pending → running, current_stage='listing'.
- on_stage_transition(stage): running, processed_count reset.
- on_progress(processed, total): running, counters updated.
- on_complete(result_dir): running → completed, current_stage='done'.
- on_fail(code, detail): running → failed, error_code recorded.
- mark_interrupted_at_shutdown(): all running/pending → interrupted.

Constitution V (Local-First): no Celery/Redis. asyncio + flock only.
"""

from __future__ import annotations

import asyncio
import contextlib
import fcntl
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import IO

from tube_scout.web.errors import to_user_message
from tube_scout.web.jobs.progress import JobProgress
from tube_scout.web.paths import get_lock_dir
from tube_scout.web.repo import jobs_repo

LOGGER = logging.getLogger("tube_scout.web.jobs.runner")


class DepartmentBusyError(RuntimeError):
    """Raised when another job is already holding the per-department lock."""


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


class JobRunner:
    """Single-process job runner with per-department flock concurrency.

    Args:
        repo: Optional pre-built :class:`jobs_repo.JobsRepo`.
        pipeline_fn: Async callable
            ``(job_id: str, on_progress: Callable, resume_from: str | None) -> str``
            returning the absolute ``result_dir``. Defaults to
            :func:`tube_scout.web.jobs.pipeline.run` once T035 lands; injectable
            here so unit tests can stub the pipeline.
    """

    def __init__(
        self,
        *,
        repo: jobs_repo.JobsRepo | None = None,
        pipeline_fn: Callable[..., Awaitable[str]] | None = None,
    ) -> None:
        self._repo = repo or jobs_repo.JobsRepo()
        self._pipeline_fn = pipeline_fn  # may be None until pipeline imports
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._open_locks: dict[str, IO[bytes]] = {}

    def _lock_path(self, alias: str) -> Path:
        return get_lock_dir() / f"{alias}.lock"

    @contextlib.contextmanager
    def acquire_lock(self, alias: str):
        """Acquire an exclusive non-blocking flock keyed by department alias.

        The kernel releases the lock automatically if the process dies (ADR
        R-7), so a crashed runner does not strand the next operator.

        Args:
            alias: Department alias.

        Yields:
            None inside the locked region.

        Raises:
            DepartmentBusyError: When another holder already owns the lock.
        """
        if not alias:
            raise ValueError("alias must be a non-empty string")
        get_lock_dir().mkdir(parents=True, exist_ok=True)
        path = self._lock_path(alias)
        handle = path.open("w+b")
        try:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise DepartmentBusyError(
                    f"another job is running for department alias={alias}"
                ) from exc
            self._open_locks[alias] = handle
            yield
        finally:
            self._open_locks.pop(alias, None)
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            finally:
                handle.close()

    async def run_job(
        self,
        job_id: str,
        *,
        department_alias: str,
        resume_from: str | None = None,
    ) -> None:
        """Execute the pipeline for ``job_id`` under the department's flock.

        Args:
            job_id: New job identifier (already inserted as pending).
            department_alias: Department alias for the per-dept lock.
            resume_from: Optional original job_id for checkpoint resume
                (T073 retry route).

        Raises:
            DepartmentBusyError: If the alias is already locked.
        """
        if not job_id:
            raise ValueError("job_id must be a non-empty string")
        if not department_alias:
            raise ValueError("department_alias must be a non-empty string")
        if self._pipeline_fn is None:
            raise RuntimeError(
                "JobRunner.pipeline_fn not set; T035 pipeline must be wired"
            )
        with self.acquire_lock(department_alias):
            self._repo.transition_to(
                job_id, status="running", current_stage="listing"
            )

            def _on_progress(
                stage: str, processed: int, total: int
            ) -> None:
                self._repo.transition_to(
                    job_id, status="running", current_stage=stage
                )
                self._repo.update_progress(
                    job_id,
                    processed_count=processed,
                    total_count=total,
                )

            try:
                result_dir = await self._pipeline_fn(
                    job_id,
                    on_progress=_on_progress,
                    resume_from=resume_from,
                )
            except _PipelineError as exc:
                self._repo.transition_to(
                    job_id,
                    status="failed",
                    error_code=exc.code,
                    error_detail=exc.detail,
                    completed_at=_utc_now_iso(),
                )
                LOGGER.exception(
                    "pipeline failed for job %s: code=%s", job_id, exc.code
                )
                return
            except Exception as exc:
                self._repo.transition_to(
                    job_id,
                    status="failed",
                    error_code="pipeline.internal",
                    error_detail=str(exc),
                    completed_at=_utc_now_iso(),
                )
                LOGGER.exception("unexpected pipeline error for job %s", job_id)
                return
            self._repo.transition_to(
                job_id,
                status="completed",
                current_stage="done",
                completed_at=_utc_now_iso(),
            )
            # result_dir persistence happens in results_repo via the pipeline
            # callback; runner only owns the job state machine.

    def spawn(
        self,
        job_id: str,
        *,
        department_alias: str,
        resume_from: str | None = None,
    ) -> asyncio.Task[None]:
        """Schedule :meth:`run_job` as a fire-and-forget asyncio Task."""
        task = asyncio.create_task(
            self.run_job(
                job_id,
                department_alias=department_alias,
                resume_from=resume_from,
            ),
            name=f"tube-scout-job-{job_id}",
        )
        self._tasks[job_id] = task
        task.add_done_callback(lambda _t: self._tasks.pop(job_id, None))
        return task

    def mark_interrupted_at_shutdown(self) -> None:
        """Mark all pending/running jobs as interrupted (ADR R-1).

        Called from the lifespan shutdown hook so a server restart does not
        leave abandoned 'running' rows in the table.
        """
        ids = self._repo.list_running_at_shutdown()
        for job_id in ids:
            self._repo.transition_to(
                job_id,
                status="interrupted",
                completed_at=_utc_now_iso(),
            )

    def render_progress(self, job_id: str) -> JobProgress:
        """Build the in-memory :class:`JobProgress` snapshot for the route.

        The route serializer formats this into the JSON payload defined by
        ``GET /jobs/{id}/progress``.
        """
        row = self._repo.find_by_id(job_id)
        if row is None:
            raise KeyError(job_id)
        kr_message = (
            to_user_message(_progress_code(row.error_code))
            if row.error_code
            else None
        )
        return JobProgress(
            job_id=row.job_id,
            status=row.status,
            current_stage=row.current_stage,
            processed_count=row.processed_count,
            total_count=row.total_count,
            started_at=row.started_at,
            completed_at=row.completed_at,
            error_code=row.error_code,
            error_message_kr=kr_message,
        )


def _progress_code(error_code: str) -> str:
    """Map a pipeline error code into the errors.py key namespace."""
    if "." in error_code:
        return error_code
    return f"pipeline.{error_code}"


class _PipelineError(Exception):
    """Internal raise channel from the pipeline to mark a typed failure."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


# Re-exported so pipeline.py can ``from runner import PipelineError``.
PipelineError = _PipelineError
