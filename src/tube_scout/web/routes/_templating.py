"""Shared Jinja2 environment + render helper (T056-T064 support).

Single Jinja2 environment instance — Starlette ``request.app.state.templates``
holds it after :func:`install_templates` is called from ``create_app``. The
render helper keeps route handlers tiny (HTML response with status code +
content_type set correctly).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape
from starlette.requests import Request
from starlette.responses import HTMLResponse

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"


def build_environment() -> Environment:
    """Return a fresh Jinja2 environment for the admin web UI templates."""
    return Environment(
        loader=FileSystemLoader(str(_TEMPLATES_DIR)),
        autoescape=select_autoescape(("html",)),
        trim_blocks=True,
        lstrip_blocks=True,
    )


def install_templates(app) -> Environment:
    """Attach a built environment to ``app.state.templates`` once at startup."""
    env = build_environment()
    app.state.templates = env
    return env


def render_template(
    request: Request,
    name: str,
    context: dict[str, Any] | None = None,
    *,
    status_code: int = 200,
) -> HTMLResponse:
    """Render ``name`` with ``context`` and return an :class:`HTMLResponse`.

    Args:
        request: Starlette request (carries ``app.state.templates``).
        name: Template filename (e.g. ``login.html``).
        context: Optional template context dict.
        status_code: HTTP status code for the response.

    Returns:
        :class:`HTMLResponse` with charset=utf-8 (Korean rendering).
    """
    env: Environment = (
        getattr(request.app.state, "templates", None) or build_environment()
    )
    template = env.get_template(name)
    body = template.render(**(context or {}))
    return HTMLResponse(content=body, status_code=status_code)
