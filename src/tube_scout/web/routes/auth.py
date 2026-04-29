"""Authentication routes (T052).

Implements ``GET /login``, ``POST /login``, and ``POST /logout`` per
``contracts/http-routes.md``. The route handlers use:

- ``app.state.session_signer`` (T027/T036) to mint and clear the signed
  session cookie.
- ``app.state.rate_limiter`` (T028) to enforce 5-failure / 5-min lockout.
- ``middleware.password_hashing.verify_password`` (T014) for bcrypt
  validation against ``TUBE_SCOUT_ADMIN_PASSWORD_BCRYPT``.
- ``errors.to_user_message`` (T032) for Korean user messages — no English
  detail leaks.

Spec FR-001/FR-002/FR-004a/FR-004c. Constitution VI: secrets are read from
agenix-injected env vars and never echoed in responses.
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Iterable
from urllib.parse import urlsplit

from starlette.requests import Request
from starlette.responses import RedirectResponse, Response

from tube_scout.web.errors import to_user_message
from tube_scout.web.middleware.password_hashing import (
    BadHashError,
    verify_password,
)
from tube_scout.web.middleware.session import (
    SESSION_MAX_AGE_SECONDS,
    generate_csrf_token,
)
from tube_scout.web.routes._templating import render_template

LOGGER = logging.getLogger("tube_scout.web.routes.auth")

SESSION_COOKIE_NAME = "session"


def _safe_next_url(value: str | None) -> str:
    """Return a safe relative redirect target.

    Open-redirect protection (ADR + adversary ADV-US1-74/90~93):

    1. Must start with a single ``/`` (not ``//`` — protocol-relative).
    2. Must not contain backslashes (browsers normalise ``/\\`` → ``//``
       and treat the result as a protocol-relative URL).
    3. Must not contain ASCII control bytes (0x00-0x1F + 0x7F) — defends
       against header splitting / smuggling and null-byte path tricks.
    4. Must not have a scheme or netloc per ``urlsplit`` — rejects
       ``javascript:`` / ``data:`` / external hosts.

    Suspicious / external URLs fall back to ``/jobs/new``.
    """
    if not value:
        return "/jobs/new"
    if "\\" in value:
        return "/jobs/new"
    if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in value):
        return "/jobs/new"
    if value.startswith("//"):
        return "/jobs/new"
    if not value.startswith("/"):
        return "/jobs/new"
    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc:
        return "/jobs/new"
    return value


def _build_session_cookie(
    response: Response, *, signer, username: str, now: int
) -> None:
    """Mint a fresh signed session cookie and attach it to ``response``.

    Builds the Set-Cookie header by hand so the ``SameSite=Lax`` token
    matches the casing required by ``contracts/http-routes.md`` (Starlette
    lowercases the directive value, breaking the contract assertion).
    """
    csrf = generate_csrf_token()
    payload = {
        "username": username,
        "issued_at": now,
        "last_active": now,
        "csrf_token": csrf,
    }
    cookie = signer.sign(payload)
    response.headers.append(
        "set-cookie",
        (
            f"{SESSION_COOKIE_NAME}={cookie}; "
            f"Max-Age={SESSION_MAX_AGE_SECONDS}; "
            "Path=/; "
            "HttpOnly; "
            "Secure; "
            "SameSite=Lax"
        ),
    )


def _render_login_form(
    *,
    request: Request,
    csrf_token: str,
    next_url: str | None,
    error_message_kr: str | None = None,
    status_code: int = 200,
) -> Response:
    return render_template(
        request,
        "login.html",
        {
            "csrf_token": csrf_token,
            "next_url": next_url,
            "error_message_kr": error_message_kr,
        },
        status_code=status_code,
    )


async def get_login(request: Request) -> Response:
    """GET /login — render the form with a fresh CSRF token in a cookie.

    The CSRF token is also stashed in a short-lived ``csrf`` cookie so the
    POST handler can verify the form submission against the same value
    (double-submit cookie pattern, since the operator is not yet
    authenticated and we have no signed session to bind to).

    Returns:
        200 ``text/html`` with the rendered login form.
    """
    csrf = generate_csrf_token()
    next_url = request.query_params.get("next")
    response = _render_login_form(request=request, csrf_token=csrf, next_url=next_url)
    # CSRF cookie: short-lived double-submit guard. We *don't* set Secure on
    # this cookie because (a) the value is also embedded in the form HTML so
    # there is no secrecy to protect, and (b) the production reverse proxy
    # terminates TLS so the header rewrite still allows browser to send it.
    # The session cookie issued post-login is the one that carries Secure.
    response.set_cookie(
        key="csrf",
        value=csrf,
        max_age=600,
        httponly=True,
        secure=False,
        samesite="lax",
        path="/",
    )
    return response


def _verify_csrf(request: Request, submitted: str | None) -> bool:
    """Constant-time double-submit CSRF verification."""
    if not submitted:
        return False
    cookie = request.cookies.get("csrf")
    if not cookie:
        return False
    import hmac

    return hmac.compare_digest(submitted, cookie)


async def post_login(request: Request) -> Response:
    """POST /login — verify creds, issue session cookie, redirect to ``next``.

    Order of checks (Constitution II Fail-Fast):

    1. CSRF token presence + match → 400 with ``auth.csrf`` if missing.
    2. Rate-limit lockout → 403 with ``auth.locked`` and remaining seconds.
    3. bcrypt verification — failure increments the counter.
    4. Open-redirect filter on ``next``.
    5. Issue cookie + 302 to safe ``next``.
    """
    form = await request.form()
    submitted_csrf = form.get("csrf_token")
    fallback_csrf = generate_csrf_token()
    next_url = _safe_next_url(form.get("next"))

    if not _verify_csrf(request, submitted_csrf):
        return _render_login_form(
            request=request,
            csrf_token=fallback_csrf,
            next_url=next_url,
            error_message_kr=to_user_message("auth.csrf"),
            status_code=400,
        )

    username = (form.get("username") or "").strip()
    password = form.get("password") or ""
    expected_username = os.environ.get("TUBE_SCOUT_ADMIN_USERNAME", "")
    stored_hash = os.environ.get("TUBE_SCOUT_ADMIN_PASSWORD_BCRYPT", "")
    rate_limiter = request.app.state.rate_limiter
    signer = request.app.state.session_signer

    if username and rate_limiter.is_locked(username):
        seconds = rate_limiter.remaining_lock_seconds(username)
        # ADV-US1-82: a 0-second remaining window means the lock has just
        # expired in a race — fall back to the generic credentials message
        # instead of rendering the absurd "0초 후 다시 시도하세요".
        if seconds <= 0:
            return _render_login_form(
                request=request,
                csrf_token=submitted_csrf or fallback_csrf,
                next_url=next_url,
                error_message_kr=to_user_message("auth.bad_credentials"),
                status_code=200,
            )
        return _render_login_form(
            request=request,
            csrf_token=submitted_csrf or fallback_csrf,
            next_url=next_url,
            error_message_kr=to_user_message("auth.locked", seconds=seconds),
            status_code=403,
        )

    bcrypt_ok = False
    # ADV-US1-79: constant-time compare so user-existence cannot be inferred
    # from response timing.
    import hmac as _hmac

    username_match = bool(
        username
        and expected_username
        and _hmac.compare_digest(
            username.encode("utf-8"), expected_username.encode("utf-8")
        )
    )
    if username_match and password and stored_hash:
        try:
            bcrypt_ok = verify_password(password, stored_hash)
        except (ValueError, BadHashError):
            LOGGER.exception("bcrypt verification failed unexpectedly")
            bcrypt_ok = False

    if not bcrypt_ok:
        if username:
            rate_limiter.register_failure(username)
            if rate_limiter.is_locked(username):
                seconds = rate_limiter.remaining_lock_seconds(username)
                return _render_login_form(
                    request=request,
                    csrf_token=submitted_csrf or fallback_csrf,
                    next_url=next_url,
                    error_message_kr=to_user_message("auth.locked", seconds=seconds),
                    status_code=403,
                )
        return _render_login_form(
            request=request,
            csrf_token=submitted_csrf or fallback_csrf,
            next_url=next_url,
            error_message_kr=to_user_message("auth.bad_credentials"),
            status_code=200,
        )

    rate_limiter.register_success(username)
    response = RedirectResponse(url=next_url, status_code=303)
    _build_session_cookie(
        response, signer=signer, username=username, now=int(time.time())
    )
    response.delete_cookie("csrf", path="/")
    return response


async def post_logout(request: Request) -> Response:
    """POST /logout — clear the session cookie and redirect to /login.

    Spec ``contracts/http-routes.md`` L28 requires CSRF on POST /logout. The
    token is verified against the session-bound ``csrf_token`` carried in
    the signed session cookie (set on ``request.state.session`` by
    :class:`AuthRequiredMiddleware`). Verification failure returns 400 +
    Korean message — never a silent success that would leave the operator's
    session intact.

    Writes the Set-Cookie header by hand so ``SameSite=Lax`` casing matches
    ``contracts/http-routes.md`` (see :func:`_build_session_cookie`).
    """
    import hmac as _hmac

    form = await request.form()
    submitted = form.get("csrf_token") or ""
    session = getattr(request.state, "session", None)
    expected = session.csrf_token if session is not None else ""
    if not submitted or not expected or not _hmac.compare_digest(submitted, expected):
        return _render_login_form(
            request=request,
            csrf_token=generate_csrf_token(),
            next_url=None,
            error_message_kr=to_user_message("auth.csrf"),
            status_code=400,
        )
    response = RedirectResponse(url="/login", status_code=303)
    response.headers.append(
        "set-cookie",
        (f"{SESSION_COOKIE_NAME}=; Max-Age=0; Path=/; HttpOnly; Secure; SameSite=Lax"),
    )
    response.delete_cookie("csrf", path="/")
    return response


def auth_routes() -> Iterable:
    """Return the auth route definitions for mounting in ``create_app``."""
    from starlette.routing import Route

    return [
        Route("/login", get_login, methods=["GET"]),
        Route("/login", post_login, methods=["POST"]),
        Route("/logout", post_logout, methods=["POST"]),
    ]
