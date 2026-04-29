"""Reuse-detection pair review route (T074).

POST /jobs/{job_id}/reviews/{pair_id} — operator marks a pair as
``confirmed_duplicate`` / ``false_positive`` / ``unreviewed`` per spec
FR-019. The result is persisted via :class:`ReviewsRepo.upsert_review`
so the next analysis can filter the pair out (FR-020).
"""

from __future__ import annotations

import hmac
import logging
from collections.abc import Iterable

from starlette.requests import Request
from starlette.responses import RedirectResponse, Response
from starlette.routing import Route

from tube_scout.web.errors import to_user_message
from tube_scout.web.repo import jobs_repo, reviews_repo
from tube_scout.web.routes._templating import render_template

LOGGER = logging.getLogger("tube_scout.web.routes.reviews")

VALID_STATUSES: frozenset[str] = frozenset(
    {"unreviewed", "confirmed_duplicate", "false_positive"}
)


def _verify_csrf(request: Request, submitted: str | None) -> bool:
    if not submitted:
        return False
    session = getattr(request.state, "session", None)
    if session is None:
        return False
    return hmac.compare_digest(submitted, session.csrf_token)


def _csrf_token(request: Request) -> str:
    session = getattr(request.state, "session", None)
    return session.csrf_token if session is not None else ""


def _kr_error(request: Request, code: str, status_code: int) -> Response:
    return render_template(
        request,
        "error.html",
        {
            "error_message_kr": to_user_message(code),
            "csrf_token": _csrf_token(request),
        },
        status_code=status_code,
    )


async def post_review(request: Request) -> Response:
    """POST a review for a single pair.

    Validation:
    - CSRF token must match the session-bound csrf_token.
    - Pair must exist (or be a known unreviewed candidate from the job's
      reuse detection output).
    - Status MUST be in :data:`VALID_STATUSES`.
    - Note (optional) MUST be ≤ 512 characters.
    """
    job_id = request.path_params["job_id"]
    pair_id = request.path_params["pair_id"]

    form = await request.form()
    submitted_csrf = form.get("csrf_token")
    if not _verify_csrf(request, submitted_csrf):
        return _kr_error(request, "auth.csrf", status_code=400)

    status_value = (form.get("status") or "").strip()
    if status_value not in VALID_STATUSES:
        return _kr_error(request, "review.invalid_status", status_code=400)

    note = form.get("note")
    if note is not None and len(note) > 512:
        return _kr_error(request, "review.note_too_long", status_code=400)

    job = jobs_repo.JobsRepo().find_by_id(job_id)
    if job is None:
        return _kr_error(request, "files.missing", status_code=404)

    repo = reviews_repo.ReviewsRepo()
    existing = repo.find_by_pair(pair_id)
    if existing is None:
        return _kr_error(request, "files.missing", status_code=404)
    # ADV-US2-22 (IDOR): the pair MUST belong to the job in the URL.
    # Otherwise the request is an attempt to mutate another job's pair
    # via this job's session.
    if existing.job_id != job_id:
        LOGGER.warning(
            "rejected pair-job IDOR: pair=%s belongs to job=%s, requested via job=%s",
            pair_id,
            existing.job_id,
            job_id,
        )
        return _kr_error(request, "files.missing", status_code=404)

    session = getattr(request.state, "session", None)
    actor = session.username if session is not None else None

    repo.upsert_review(
        pair_id=pair_id,
        job_id=job_id,
        status=status_value,
        updated_by=actor,
        note=note or None,
    )

    referer = request.headers.get("referer")
    # ADV-US2-23: reuse the same open-redirect filter as login.next so a
    # backslash / control-char / scheme-bearing referer cannot drive an
    # external redirect.
    from tube_scout.web.routes.auth import _safe_next_url

    if referer and _safe_next_url(referer) == referer:
        target = referer
    else:
        target = f"/jobs/{job_id}/results"
    return RedirectResponse(url=target, status_code=303)


def reviews_routes() -> Iterable[Route]:
    return [
        Route(
            "/jobs/{job_id}/reviews/{pair_id}",
            post_review,
            methods=["POST"],
        )
    ]
