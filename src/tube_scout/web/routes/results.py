"""Results page + file download routes (T055).

Endpoints:

- ``GET /jobs/{job_id}/results`` — render the result page with 5 download
  links + matched-video count + priority summary table.
- ``GET /jobs/{job_id}/files/{kind}`` — serve the requested artifact with
  RFC-5987 ``Content-Disposition`` and traversal protection.

Spec FR-016, FR-018. Constitution VI: error responses surface only Korean
user messages — internal absolute paths never leak.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from pathlib import Path

from starlette.requests import Request
from starlette.responses import FileResponse, Response
from starlette.routing import Route

from tube_scout.web.errors import to_user_message
from tube_scout.web.repo import jobs_repo, results_repo, reviews_repo
from tube_scout.web.repo.departments_repo import DepartmentsRepo
from tube_scout.web.routes._templating import render_template
from tube_scout.web.routes.filenames import (
    KIND_EXTENSIONS,
    build_slug,
    content_disposition,
    content_type_for,
)

LOGGER = logging.getLogger("tube_scout.web.routes.results")


def _csrf_token(request: Request) -> str:
    session = getattr(request.state, "session", None)
    return session.csrf_token if session is not None else ""


def _resolve_artifact_path(*, result_row, kind: str, project_dir: Path) -> Path | None:
    """Map ``kind`` → result_row column → absolute path under ``project_dir``.

    Returns ``None`` if no path is recorded for that kind. The caller treats
    that as ``files.missing`` (404 Korean message).
    """
    column = {
        "v1v3-html": result_row.report_v1v3_html,
        "v1v3-pdf": result_row.report_v1v3_pdf,
        "v1v3-excel": result_row.report_v1v3_excel,
        "reuse-html": result_row.report_reuse_html,
        "reuse-excel": result_row.report_reuse_excel,
    }[kind]
    if not column:
        return None
    return Path(column).resolve()


def _is_within(path: Path, root: Path) -> bool:
    """Return True iff ``path`` is contained within ``root`` after resolution."""
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (ValueError, OSError):
        return False


def _project_dir(job_id: str) -> Path:
    from tube_scout.web.paths import get_state_dir

    return (get_state_dir() / "projects" / job_id).resolve()


async def get_results(request: Request) -> Response:
    """Render ``/jobs/{job_id}/results`` (FR-016 / SC-004)."""
    job_id = request.path_params["job_id"]
    job_repo = jobs_repo.JobsRepo()
    job_row = job_repo.find_by_id(job_id)
    if job_row is None:
        return render_template(
            request,
            "error.html",
            {
                "error_message_kr": "요청한 작업을 찾을 수 없습니다.",
                "csrf_token": _csrf_token(request),
            },
            status_code=404,
        )

    result_row = results_repo.ResultsRepo().get_result(job_id)
    departments = DepartmentsRepo()
    dept = departments.find_by_alias(job_row.department_alias)

    has_artifacts = bool(
        result_row
        and any(
            getattr(result_row, attr)
            for attr in (
                "report_v1v3_html",
                "report_v1v3_pdf",
                "report_v1v3_excel",
                "report_reuse_html",
                "report_reuse_excel",
            )
        )
    )

    review_rows = reviews_repo.ReviewsRepo().list_for_job(job_id)
    return render_template(
        request,
        "result.html",
        {
            "job_id": job_id,
            "job": job_row,
            "result": result_row,
            "department": dept,
            "has_artifacts": has_artifacts,
            "kinds": list(KIND_EXTENSIONS.keys()) if has_artifacts else [],
            "review_rows": review_rows,
            "csrf_token": _csrf_token(request),
        },
        status_code=200,
    )


async def get_file(request: Request) -> Response:
    """Serve ``/jobs/{job_id}/files/{kind}`` (FR-016/FR-018)."""
    job_id = request.path_params["job_id"]
    kind = request.path_params["kind"]

    if kind not in KIND_EXTENSIONS:
        # Unknown kind — return 404 with Korean message (no echo of input).
        return _kr_404(request, "files.unknown_kind")

    job_row = jobs_repo.JobsRepo().find_by_id(job_id)
    if job_row is None:
        return _kr_404(request, "files.missing")

    result_row = results_repo.ResultsRepo().get_result(job_id)
    if result_row is None:
        return _kr_404(request, "files.missing")

    path = _resolve_artifact_path(
        result_row=result_row, kind=kind, project_dir=_project_dir(job_id)
    )
    if path is None:
        return _kr_404(request, "files.missing")

    project_root = _project_dir(job_id)
    if not _is_within(path, project_root):
        LOGGER.warning("rejected file traversal attempt: job=%s kind=%s", job_id, kind)
        return _kr_404(request, "files.traversal")

    if not path.exists() or not path.is_file():
        return _kr_404(request, "files.missing")

    departments = DepartmentsRepo()
    dept = departments.find_by_alias(job_row.department_alias)
    display_name = dept.display_name if dept is not None else job_row.department_alias

    slug = build_slug(
        display_name=display_name,
        professor_name=job_row.professor_name,
        course_name=job_row.course_name,
        period_start=str(job_row.period_start),
        period_end=str(job_row.period_end),
    )
    cd = content_disposition(slug=slug, kind=kind)
    media_type = content_type_for(kind)
    response = FileResponse(path=str(path), media_type=media_type)
    response.headers["content-disposition"] = cd
    return response


def _kr_404(request: Request, code: str) -> Response:
    """Return a 404 error page (HTML) with the mapped Korean message."""
    return render_template(
        request,
        "error.html",
        {
            "error_message_kr": to_user_message(code),
            "csrf_token": _csrf_token(request),
        },
        status_code=404,
    )


def results_routes() -> Iterable[Route]:
    return [
        Route("/jobs/{job_id}/results", get_results, methods=["GET"]),
        Route("/jobs/{job_id}/files/{kind}", get_file, methods=["GET"]),
    ]
