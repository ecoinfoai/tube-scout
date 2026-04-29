"""Job submission routes (T053 + T054).

Endpoints:

- ``GET /jobs/new`` — analysis form with department dropdown (FR-005~006).
- ``POST /jobs`` — validate inputs, insert pending job, spawn background
  pipeline (FR-007~011, FR-028).
- ``GET /jobs/{job_id}`` — branch by status: ``pending``/``running`` →
  progress page; ``completed`` → results page; ``failed``/``interrupted`` →
  error page.
- ``GET /jobs/{job_id}/progress`` — JSON snapshot per ``progress.serialize``
  contract (FR-013, FR-015).

CSRF: every POST verifies ``csrf_token`` against the session-bound token in
``request.state.session`` (set by AuthRequiredMiddleware).

Constitution IV: routes are thin — all stage logic lives in services or
``cli.collect._collect_all_for_web`` (T035-bis).
"""

from __future__ import annotations

import hmac
import logging
from collections.abc import Iterable
from datetime import UTC, date, datetime

from pydantic import TypeAdapter, ValidationError
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse, Response
from starlette.routing import Route

from tube_scout.web.errors import to_user_message
from tube_scout.web.jobs.progress import serialize, stage_label_kr
from tube_scout.web.jobs.runner import JobRunner
from tube_scout.web.models import (
    CourseNameStr,
    JobIdStr,
    ProfessorNameStr,
)
from tube_scout.web.repo import jobs_repo
from tube_scout.web.repo.departments_repo import DepartmentsRepo
from tube_scout.web.routes._templating import render_template

LOGGER = logging.getLogger("tube_scout.web.routes.jobs")

_PROFESSOR_ADAPTER = TypeAdapter(ProfessorNameStr)
_COURSE_ADAPTER = TypeAdapter(CourseNameStr)
_JOB_ID_ADAPTER = TypeAdapter(JobIdStr)


def _verify_csrf(request: Request, submitted: str | None) -> bool:
    if not submitted:
        return False
    session = getattr(request.state, "session", None)
    if session is None:
        return False
    return hmac.compare_digest(submitted, session.csrf_token)


def _csrf_token(request: Request) -> str:
    """Return the CSRF token bound to the active session."""
    session = getattr(request.state, "session", None)
    return session.csrf_token if session is not None else ""


def _next_job_id(repo: jobs_repo.JobsRepo, *, base: datetime | None = None) -> str:
    """Mint a ``YYYYMMDD-HHMMSS[-N]`` job_id, suffixing N on collision."""
    base_dt = base or datetime.now(UTC)
    base_id = base_dt.strftime("%Y%m%d-%H%M%S")
    if repo.find_by_id(base_id) is None:
        return base_id
    for n in range(1, 100):
        candidate = f"{base_id}-{n}"
        if repo.find_by_id(candidate) is None:
            return candidate
    raise RuntimeError("could not allocate a unique job_id (100 collisions)")


def _validate_payload(
    *,
    department_alias: str,
    professor_name: str,
    course_name: str,
    period_start: str,
    period_end: str,
    departments_repo: DepartmentsRepo,
) -> tuple[str | None, dict]:
    """Return ``(error_code, normalized_payload)``.

    ``error_code`` is None when validation passes. The normalized payload
    has ``period_start``/``period_end`` parsed to :class:`date` objects.
    """
    if departments_repo.find_by_alias(department_alias) is None:
        return "form.department_unknown", {}

    professor = (professor_name or "").strip()
    try:
        _PROFESSOR_ADAPTER.validate_python(professor)
    except ValidationError:
        return "form.professor_invalid", {}

    course = (course_name or "").strip()
    try:
        _COURSE_ADAPTER.validate_python(course)
    except ValidationError:
        return "form.course_invalid", {}

    try:
        ps = date.fromisoformat(period_start)
        pe = date.fromisoformat(period_end)
    except ValueError:
        return "form.period_inverted", {}

    if ps > pe:
        return "form.period_inverted", {}
    if ps > date.today():
        return "form.period_future", {}

    return None, {
        "department_alias": department_alias,
        "professor_name": professor,
        "course_name": course,
        "period_start": ps,
        "period_end": pe,
    }


def _render_form(
    request: Request,
    *,
    error_code: str | None = None,
    form: dict | None = None,
    status_code: int = 200,
) -> Response:
    repo = DepartmentsRepo()
    return render_template(
        request,
        "form.html",
        {
            "csrf_token": _csrf_token(request),
            "departments": repo.list_all(),
            "form": form or {},
            "error_message_kr": to_user_message(error_code) if error_code else None,
        },
        status_code=status_code,
    )


def _percent(processed: int, total: int) -> int:
    if total <= 0:
        return 0
    return min(100, round(processed / total * 100))


async def get_jobs_new(request: Request) -> Response:
    """GET /jobs/new — render the analysis-start form."""
    return _render_form(request)


async def post_jobs(request: Request) -> Response:
    """POST /jobs — validate, insert pending row, spawn background runner."""
    form = await request.form()
    submitted_csrf = form.get("csrf_token")

    if not _verify_csrf(request, submitted_csrf):
        return _render_form(
            request,
            error_code="auth.csrf",
            form={k: form.get(k) for k in form.keys()},
            status_code=400,
        )

    payload_form = {
        "department_alias": form.get("department_alias", ""),
        "professor_name": form.get("professor_name", ""),
        "course_name": form.get("course_name", ""),
        "period_start": form.get("period_start", ""),
        "period_end": form.get("period_end", ""),
    }

    departments = DepartmentsRepo()
    error_code, normalized = _validate_payload(
        **payload_form, departments_repo=departments
    )
    if error_code:
        return _render_form(
            request, error_code=error_code, form=payload_form, status_code=200
        )

    repo = jobs_repo.JobsRepo()
    in_progress = repo.find_in_progress_for_department(normalized["department_alias"])
    if in_progress:
        return _render_form(
            request,
            error_code="form.same_department_running",
            form=payload_form,
            status_code=409,
        )

    runner: JobRunner = request.app.state.runner
    started_at = datetime.now(UTC).isoformat()
    job_id = _next_job_id(repo)
    session = getattr(request.state, "session", None)
    actor = session.username if session is not None else "anonymous"

    repo.insert_pending(
        {
            "job_id": job_id,
            "department_alias": normalized["department_alias"],
            "professor_name": normalized["professor_name"],
            "course_name": normalized["course_name"],
            "period_start": normalized["period_start"].isoformat(),
            "period_end": normalized["period_end"].isoformat(),
            "started_at": started_at,
            "created_by": actor,
        }
    )

    try:
        runner.spawn(job_id, department_alias=normalized["department_alias"])
    except RuntimeError as exc:
        # ADV-US2-21: spawn failure must transition the inserted job to
        # ``failed`` so the operator sees the Korean error and the row
        # does not stick around as a stuck pending forever.
        LOGGER.exception("runner.spawn failed for job %s: %s", job_id, exc)
        repo.transition_to(
            job_id,
            status="failed",
            error_code="pipeline.runner_unavailable",
            error_detail=str(exc),
            completed_at=datetime.now(UTC).isoformat(),
        )

    return RedirectResponse(url=f"/jobs/{job_id}", status_code=303)


async def get_job_router(request: Request) -> Response:
    """GET /jobs/{job_id} — render progress or results based on state.

    - ``pending``/``running`` → progress page.
    - ``completed`` → 303 redirect to ``/jobs/{id}/results`` (cleaner cache
      semantics than rendering inline).
    - ``failed``/``interrupted`` → error page (template TBD; currently
      progress page with status banner suffices).
    """
    job_id = request.path_params["job_id"]
    row = jobs_repo.JobsRepo().find_by_id(job_id)
    if row is None:
        return render_template(
            request,
            "error.html",
            {
                "error_message_kr": "요청한 작업을 찾을 수 없습니다.",
                "job_id": job_id,
            },
            status_code=404,
        )

    if row.status == "completed":
        return RedirectResponse(url=f"/jobs/{job_id}/results", status_code=303)

    if row.status in {"failed", "interrupted"}:
        return render_template(
            request,
            "error.html",
            {
                "error_message_kr": to_user_message(
                    f"pipeline.{row.error_code}"
                    if row.error_code and "." not in row.error_code
                    else (row.error_code or "pipeline.internal")
                ),
                "job_id": job_id,
            },
            status_code=200,
        )

    label = stage_label_kr(row.current_stage) if row.current_stage else None
    return render_template(
        request,
        "progress.html",
        {
            "job_id": job_id,
            "job": row,
            "stage_label_kr": label,
            "percent": _percent(row.processed_count, row.total_count),
        },
        status_code=200,
    )


async def get_progress(request: Request) -> Response:
    """GET /jobs/{job_id}/progress — JSON progress snapshot (FR-013)."""
    job_id = request.path_params["job_id"]
    runner: JobRunner = request.app.state.runner
    try:
        snapshot = runner.render_progress(job_id)
    except KeyError:
        return JSONResponse(
            {
                "error_code": "job.not_found",
                "error_message_kr": "요청한 작업을 찾을 수 없습니다.",
            },
            status_code=404,
        )
    return JSONResponse(serialize(snapshot), status_code=200)


async def post_retry(request: Request) -> Response:
    """POST /jobs/{job_id}/retry — checkpoint resume (FR-022a, T073).

    Validation:
    - CSRF must match the session-bound csrf_token.
    - Original status MUST be ``failed`` or ``interrupted`` (else 409).

    On success: insert a new ``pending`` job with the same form fields,
    spawn the runner with ``resume_from=original_id`` so the pipeline can
    skip already-completed stages, and 302 → ``/jobs/{new_id}``.
    """
    original_id = request.path_params["job_id"]
    form = await request.form()
    submitted_csrf = form.get("csrf_token")
    if not _verify_csrf(request, submitted_csrf):
        return render_template(
            request,
            "error.html",
            {
                "error_message_kr": to_user_message("auth.csrf"),
                "csrf_token": _csrf_token(request),
            },
            status_code=400,
        )

    repo = jobs_repo.JobsRepo()
    original = repo.find_by_id(original_id)
    if original is None:
        return render_template(
            request,
            "error.html",
            {
                "error_message_kr": "요청한 작업을 찾을 수 없습니다.",
                "csrf_token": _csrf_token(request),
            },
            status_code=404,
        )

    if original.status not in {"failed", "interrupted"}:
        return render_template(
            request,
            "error.html",
            {
                "error_message_kr": to_user_message("retry.invalid_state"),
                "job_id": original_id,
                "csrf_token": _csrf_token(request),
            },
            status_code=409,
        )

    runner: JobRunner = request.app.state.runner
    started_at = datetime.now(UTC).isoformat()
    new_id = _next_job_id(repo)
    session = getattr(request.state, "session", None)
    actor = session.username if session is not None else "anonymous"

    repo.insert_pending(
        {
            "job_id": new_id,
            "department_alias": original.department_alias,
            "professor_name": original.professor_name,
            "course_name": original.course_name,
            "period_start": original.period_start,
            "period_end": original.period_end,
            "started_at": started_at,
            "created_by": actor,
        }
    )

    try:
        runner.spawn(
            new_id,
            department_alias=original.department_alias,
            resume_from=original_id,
        )
    except RuntimeError as exc:
        # ADV-US2-21: spawn failure on retry must also flip the new job
        # to ``failed`` (mirror of post_jobs).
        LOGGER.exception("runner.spawn failed for retry %s: %s", new_id, exc)
        repo.transition_to(
            new_id,
            status="failed",
            error_code="pipeline.runner_unavailable",
            error_detail=str(exc),
            completed_at=datetime.now(UTC).isoformat(),
        )

    return RedirectResponse(url=f"/jobs/{new_id}", status_code=303)


def jobs_routes() -> Iterable[Route]:
    """Return the job-submission route definitions."""
    return [
        Route("/jobs/new", get_jobs_new, methods=["GET"]),
        Route("/jobs", post_jobs, methods=["POST"]),
        Route("/jobs/{job_id}/retry", post_retry, methods=["POST"]),
        Route("/jobs/{job_id}", get_job_router, methods=["GET"]),
        Route("/jobs/{job_id}/progress", get_progress, methods=["GET"]),
    ]
