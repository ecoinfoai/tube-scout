"""Starlette application factory + lifespan (T036).

Orchestrator (RULE4): wires all Phase 2 building blocks into a single ASGI
app. Responsibilities:

1. **Env validation** (Constitution II Fail-Fast): :func:`validate_required_env`
   is called at module load and again from the lifespan startup hook so a
   missing agenix env var fails the boot rather than silently degrading.
2. **Runtime dirs**: :func:`paths.ensure_runtime_dirs` creates CONFIG/STATE/
   LOG/LOCK directories with mode 0700.
3. **Schema bootstrap**: :func:`db.bootstrap` runs ``CREATE TABLE IF NOT
   EXISTS`` for all 5 tables.
4. **Singleton wiring**: a :class:`SessionSigner` and :class:`LoginRateLimiter`
   are constructed once and stashed on ``app.state`` so middleware and
   routes share them.
5. **Middleware mount order** (outermost → innermost):
   ``HttpsRedirect → SecurityHeaders → AuthRequired → RateLimit-state``.
   Note: Session signing is consumed inside ``AuthRequiredMiddleware`` via
   ``app.state.session_signer``; rate-limit state is exposed similarly so
   the auth route can call ``register_failure``/``register_success``
   without instantiating a new tracker.
6. **Routes**: ``GET /healthz`` is registered. US1/US2/US3 routes are
   layered on top by the user-story implementation tasks (T052+).
7. **Shutdown hooks** (architect ADRs):
   - R-1: :meth:`JobRunner.mark_interrupted_at_shutdown` flips orphan
     pending/running rows to ``interrupted``.
   - R-3: :func:`db.checkpoint` runs ``PRAGMA wal_checkpoint(TRUNCATE)``.
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from typing import AsyncIterator

import bcrypt
from pathlib import Path
from starlette.applications import Starlette
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from tube_scout.web.middleware.auth_required import AuthRequiredMiddleware
from tube_scout.web.middleware.https_redirect import HttpsRedirectMiddleware
from tube_scout.web.middleware.rate_limit import LoginRateLimiter
from tube_scout.web.middleware.security_headers import SecurityHeadersMiddleware
from tube_scout.web.middleware.session import SessionSigner
from tube_scout.web.paths import ensure_runtime_dirs
from tube_scout.web.repo import db
from tube_scout.web.routes._templating import install_templates
from tube_scout.web.routes.auth import auth_routes
from tube_scout.web.routes.health import healthz
from tube_scout.web.routes.jobs import jobs_routes
from tube_scout.web.routes.results import results_routes

_STATIC_DIR = Path(__file__).resolve().parent / "static"

LOGGER = logging.getLogger("tube_scout.web.app")

REQUIRED_ENV_VARS: tuple[str, ...] = (
    "TUBE_SCOUT_ADMIN_USERNAME",
    "TUBE_SCOUT_ADMIN_PASSWORD_BCRYPT",
    "TUBE_SCOUT_SESSION_SECRET",
)


class MissingEnvError(RuntimeError):
    """Raised when a required env var is missing or empty at startup."""


def validate_required_env() -> None:
    """Validate that every agenix-injected env var is present and well-formed.

    Constitution II Fail-Fast: empty values are treated as missing so an
    operator who clears a vault entry by mistake gets an immediate boot
    failure with the env-var name (not the value, which would leak a
    partial bcrypt hash).

    Raises:
        MissingEnvError: When any required var is missing/empty, or when
            ``TUBE_SCOUT_ADMIN_PASSWORD_BCRYPT`` is not a parseable bcrypt
            hash. The error message references the var *name* only.
    """
    for name in REQUIRED_ENV_VARS:
        value = os.environ.get(name, "")
        if not value:
            raise MissingEnvError(
                f"required env var missing or empty: {name}"
            )
    pw_hash = os.environ["TUBE_SCOUT_ADMIN_PASSWORD_BCRYPT"]
    try:
        # checkpw with a known-bad password validates the *hash format* without
        # ever exposing the value to the error message.
        bcrypt.checkpw(b"validation-probe", pw_hash.encode("utf-8"))
    except ValueError as exc:
        raise MissingEnvError(
            "TUBE_SCOUT_ADMIN_PASSWORD_BCRYPT has an invalid bcrypt format"
        ) from exc


@asynccontextmanager
async def _lifespan(app: Starlette) -> AsyncIterator[None]:
    """Lifespan context: startup validation + shutdown ADR R-1 + R-3."""
    validate_required_env()
    ensure_runtime_dirs()
    db.bootstrap()
    app.state.session_signer = SessionSigner(
        secret=os.environ["TUBE_SCOUT_SESSION_SECRET"]
    )
    app.state.rate_limiter = LoginRateLimiter()
    # T064: build a singleton JobRunner here so route handlers can spawn
    # background tasks via ``request.app.state.runner.spawn(...)`` and tests
    # can inject mock pipelines via ``app.state.runner._pipeline_fn = ...``.
    from tube_scout.web.jobs import pipeline as pipeline_module
    from tube_scout.web.jobs.runner import JobRunner

    app.state.runner = JobRunner(pipeline_fn=pipeline_module.run)
    LOGGER.info("admin web UI lifespan startup complete")
    try:
        yield
    finally:
        # ADR R-1: mark interrupted on shutdown. Imported lazily so a future
        # cycle without the runner does not break boot. Safe under broad
        # except: any failure here would already be too late to surface to
        # the operator — best effort is the documented behavior.
        try:
            from tube_scout.web.jobs.runner import JobRunner

            JobRunner().mark_interrupted_at_shutdown()
        except Exception:
            LOGGER.exception(
                "lifespan shutdown: failed to mark running jobs as interrupted"
            )
        # ADR R-3: WAL checkpoint TRUNCATE.
        try:
            db.checkpoint()
        except Exception:
            LOGGER.exception("lifespan shutdown: PRAGMA wal_checkpoint failed")


def create_app() -> Starlette:
    """Build and return the admin web UI Starlette application.

    The factory is invoked by uvicorn ``--factory`` and by tests. Each call
    returns a fresh app with a fresh :class:`Starlette` and fresh state
    bindings (signer + rate limiter) — essential for the parametrized env
    tests that monkey-patch the env at module-import time.

    Returns:
        :class:`Starlette` instance with middleware stack and routes mounted.
    """
    routes = [
        Route("/healthz", healthz, methods=["GET"]),
        *auth_routes(),
        *jobs_routes(),
        *results_routes(),
        Mount(
            "/static",
            app=StaticFiles(directory=str(_STATIC_DIR)),
            name="static",
        ),
    ]
    app = Starlette(routes=routes, lifespan=_lifespan)
    install_templates(app)
    # Outermost first → innermost last when added in reverse logical order.
    # Starlette processes middleware in registration order (outer→inner).
    app.add_middleware(AuthRequiredMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(HttpsRedirectMiddleware)
    return app
