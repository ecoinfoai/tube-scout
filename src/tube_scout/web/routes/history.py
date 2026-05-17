"""History page route (T072).

GET /history — paginated table of analysis jobs with status + department
filters per spec FR-021/FR-022 + contracts/http-routes.md.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable

from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Route

from tube_scout.web.repo import jobs_repo
from tube_scout.web.repo.departments_repo import DepartmentsRepo
from tube_scout.web.routes._templating import render_template

LOGGER = logging.getLogger("tube_scout.web.routes.history")

VALID_STATUSES: frozenset[str] = frozenset({
    "pending",
    "running",
    "completed",
    "failed",
    "interrupted",
})

STATUS_LABELS_KR: dict[str, str] = {
    "pending": "대기",
    "running": "진행 중",
    "completed": "완료",
    "failed": "실패",
    "interrupted": "중단됨",
}


def _csrf_token(request: Request) -> str:
    session = getattr(request.state, "session", None)
    return session.csrf_token if session is not None else ""


def _parse_int_query(
    request: Request, *, name: str, default: int, lo: int, hi: int
) -> int:
    """Parse a positive int query param within [lo, hi], else fall back."""
    raw = request.query_params.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    if value < lo or value > hi:
        return default
    return value


async def get_history(request: Request) -> Response:
    """Render ``/history`` with optional ``status``/``department`` filters."""
    status_raw = request.query_params.get("status")
    department = request.query_params.get("department") or None

    status_filter: list[str] = []
    if status_raw:
        for tok in status_raw.split(","):
            tok = tok.strip()
            if tok in VALID_STATUSES:
                status_filter.append(tok)

    limit = _parse_int_query(request, name="limit", default=50, lo=1, hi=200)
    offset = _parse_int_query(request, name="offset", default=0, lo=0, hi=10_000)

    filters: dict = {}
    if status_filter:
        filters["status"] = status_filter
    if department:
        filters["department"] = department

    repo = jobs_repo.JobsRepo()
    rows = repo.list_history(filters=filters, limit=limit, offset=offset)

    departments = DepartmentsRepo().list_all()
    return render_template(
        request,
        "history.html",
        {
            "rows": rows,
            "departments": departments,
            "status_options": sorted(VALID_STATUSES),
            "selected_statuses": status_filter,
            "selected_department": department or "",
            "limit": limit,
            "offset": offset,
            "status_labels_kr": STATUS_LABELS_KR,
            "csrf_token": _csrf_token(request),
        },
        status_code=200,
    )


def history_routes() -> Iterable[Route]:
    return [Route("/history", get_history, methods=["GET"])]
