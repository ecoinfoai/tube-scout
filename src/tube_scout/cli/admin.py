"""Admin CLI commands (T089-T094).

Subcommand group ``tube-scout admin ...`` for the operator (DX 지원센터장).
Spec FR-024~027 + ``contracts/admin-cli.md`` §1-§5.

Commands:
    add-department: register a new department (atomic JSON + optional OAuth).
    list:           render registered departments (rich table or JSON).
    status:         per-department OAuth token status with KR labels.
    refresh:        force OAuth token refresh.
    verify:         6-step health check.

Constitution VI (Secrets): no command prints raw token bytes; only env-var
names, expiry dates, and status enums. Constitution II (Fail-Fast): every
command validates inputs at entry and surfaces Korean error messages
without leaking internal paths.

Patchable seams (overridden in tests):
    _run_oauth_consent: OAuth consent flow trigger.
    _refresh_token:     bound credential refresh.
    _youtube_api_probe: YouTube Data API smoke test.
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import typer
from pydantic import ValidationError
from rich.console import Console
from rich.table import Table

LOGGER = logging.getLogger("tube_scout.cli.admin")

admin_app = typer.Typer(help="운영자 전용 명령")
console = Console()
err_console = Console(stderr=True)


@admin_app.callback()
def _admin_callback() -> None:
    """Run before every ``tube-scout admin`` subcommand.

    Bootstraps the runtime config/state/log/lock directories AND the
    ``admin.db`` schema so subcommands can persist without a missing-dir
    or missing-table crash. Fixes the 2026-05-18 CI failure where fresh
    runners lack ``~/.local/share/tube-scout`` (and therefore also lack
    the ``operator_actions`` table inside an absent DB).
    ``bootstrap()`` is idempotent — re-entry on warm hosts is a no-op.
    """
    from tube_scout.web.repo.db import bootstrap
    bootstrap()

NEAR_EXPIRY_DAYS = 7

# ADV-US3-12: alias regex mirrors models.AliasStr (Pydantic) so the path
# construction in _token_path cannot be coerced into a traversal even if
# departments_repo validation is skipped.
_ALIAS_RE = re.compile(r"^[a-z][a-z0-9-]{0,31}$")

# ADV-US3-14: env-var names MUST follow the agenix prefix pattern. A
# misconfigured operator could otherwise map a department's secrets onto
# arbitrary env names (including TUBE_SCOUT_ADMIN_PASSWORD_BCRYPT) and
# silently break auth.
_ENV_NAME_PATTERNS: dict[str, re.Pattern[str]] = {
    "channel_id_env": re.compile(r"^TUBE_SCOUT_CHANNEL_ID_[A-Z0-9_]+$"),
    "client_secret_env": re.compile(r"^TUBE_SCOUT_CLIENT_SECRET_[A-Z0-9_]+$"),
    "api_key_env": re.compile(r"^TUBE_SCOUT_API_KEY_[A-Z0-9_]+$"),
}


# ---------------------------------------------------------------------------
# Patchable seams (tests monkeypatch these)
# ---------------------------------------------------------------------------


def _run_oauth_consent(alias: str) -> None:
    """OAuth consent flow trigger; tests patch this to skip the browser."""
    raise NotImplementedError(
        "OAuth consent integration pending — pass --no-oauth-consent until "
        "services/auth.py exposes a non-interactive consent driver."
    )


def _refresh_token(alias: str) -> None:
    """Refresh the OAuth token for ``alias``."""
    raise NotImplementedError("token refresh integration pending — patched in tests")


def _youtube_api_probe(alias: str, channel_id: str) -> dict:
    """Probe ``channels.list`` once to confirm the alias is healthy."""
    raise NotImplementedError("YouTube API probe pending — patched in tests")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _real_uid_actor() -> str:
    """ADV-US3-16: derive actor name from real UID, never $USER.

    ``os.environ['USER']`` is attacker-controllable (``USER=spoof
    tube-scout admin ...``). ``pwd.getpwuid(os.geteuid()).pw_name``
    reflects the OS-level identity of the calling process and cannot be
    forged via env injection.
    """
    try:
        import pwd

        return pwd.getpwuid(os.geteuid()).pw_name
    except (ImportError, KeyError, OSError):
        # Non-POSIX or NSS lookup failure — fall back to a stable token
        # rather than the env-var, so audit log forgery remains impossible.
        return f"uid-{os.geteuid()}"


def _record(
    action: str, *, target_alias: str | None, result: str, detail: str | None = None
) -> None:
    from tube_scout.web.repo import operator_actions_repo

    repo = operator_actions_repo.OperatorActionsRepo()
    repo.record_action(
        action=action,
        target_alias=target_alias,
        actor=_real_uid_actor(),
        result=result,
        detail=detail,
    )


def _token_path(alias: str) -> Path:
    """Return the absolute path to the per-alias token file.

    ADV-US3-12: alias MUST match the strict regex; otherwise an attacker
    could pass ``../../../etc/passwd`` and read arbitrary files via
    ``_read_token``. The departments_repo Pydantic guard is the primary
    defence — this function is the secondary one in case operators
    bypass the repo (e.g. directly editing departments.json by hand).
    """
    if not _ALIAS_RE.fullmatch(alias):
        raise ValueError(f"alias 형식 오류 (path traversal 방지): {alias!r}")
    from tube_scout.web.paths import get_config_dir

    return get_config_dir() / "tokens" / f"{alias}_token.json"


def _read_token(alias: str) -> dict | None:
    """Return the parsed token blob for ``alias`` or ``None`` when absent.

    ADV-US3-13: corrupt JSON is logged at WARN level so the operator
    sees a hint that the file is unreadable (Constitution II silent-skip
    avoidance). Permission/IO errors (OSError other than FileNotFound)
    propagate so the operator cannot mistake a permission denied for
    ``missing``.

    ADV-US3-15: if the path is a symlink we refuse to follow it — token
    files MUST be operator-owned regular files. A symlink could redirect
    the read into ``/etc/shadow`` etc.
    """
    try:
        path = _token_path(alias)
    except ValueError:
        # ADV-US3-12 guard tripped — surface as missing without log spam.
        return None
    if path.is_symlink():
        LOGGER.warning(
            "rejected symlink token file: alias=%s path=%s",
            alias,
            path,
        )
        return None
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        # intentional-skip: corruption is reported via WARN log + caller
        # treats this as "missing"; a hard fail would block the entire
        # status command for one bad token.
        LOGGER.warning(
            "token file is corrupt JSON for alias=%s path=%s: %s",
            alias,
            path,
            exc,
        )
        return None


def _expiry_status(token: dict | None) -> tuple[str, int | None]:
    """Return ``(status, days_remaining)`` for a token blob.

    Status values: ``valid`` | ``near_expiry`` | ``expired`` | ``missing``.
    """
    if token is None:
        return ("missing", None)
    raw = token.get("expires_at")
    if not raw:
        return ("missing", None)
    try:
        expiry = datetime.fromisoformat(raw)
    except ValueError:
        return ("missing", None)
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=UTC)
    delta = expiry - datetime.now(UTC)
    days = int(delta.total_seconds() // 86400)
    if delta.total_seconds() < 0:
        return ("expired", days)
    if days <= NEAR_EXPIRY_DAYS:
        return ("near_expiry", days)
    return ("valid", days)


def _check_envs_present(*names: str) -> list[str]:
    return [n for n in names if not os.environ.get(n, "")]


# ---------------------------------------------------------------------------
# add-department
# ---------------------------------------------------------------------------


@admin_app.command("add-department")
def add_department(
    alias: str = typer.Option(..., "--alias", help="학과 alias (영문 + 숫자 + 하이픈)"),
    display: str = typer.Option(..., "--display", help="한국어 표시명 (1~32자)"),
    channel_id_env: str | None = typer.Option(
        None, "--channel-id-env", help="agenix 환경변수명 (FR-012: optional)"
    ),
    client_secret_env: str | None = typer.Option(
        None, "--client-secret-env", help="agenix 환경변수명 (FR-012: optional)"
    ),
    api_key_env: str | None = typer.Option(
        None, "--api-key-env", help="agenix 환경변수명 (FR-012: optional)"
    ),
    no_oauth_consent: bool = typer.Option(
        False, "--no-oauth-consent", help="OAuth 동의 흐름 건너뛰기"
    ),
) -> None:
    """학과를 신규 등록한다 (departments.json 원자적 쓰기 + 선택적 OAuth).

    Args:
        alias: Department alias (lowercase alphanumeric + hyphens).
        display: Korean display name (1~32 chars).
        channel_id_env: agenix env-var name for channel ID (FR-012: optional).
        client_secret_env: agenix env-var name for OAuth client secret (optional).
        api_key_env: agenix env-var name for YouTube Data API key (optional).
        no_oauth_consent: Skip the OAuth consent browser flow when True.

    Raises:
        typer.Exit: code 1 on validation failure, duplicate alias, or consent error.
    """
    from tube_scout.services.auth import load_registry
    from tube_scout.web.repo.departments_repo import (
        DepartmentsRepo,
        DuplicateAliasError,
    )

    # FR-013: OAuth env options must be all-or-nothing
    oauth_opts = {
        "channel-id-env": channel_id_env,
        "client-secret-env": client_secret_env,
        "api-key-env": api_key_env,
    }
    specified = [k for k, v in oauth_opts.items() if v is not None]
    if specified and len(specified) < 3:
        err_console.print(
            f"[red]OAuth env options must be all-or-nothing "
            f"(specified: {specified}). "
            f"Omit all three for Takeout-only registration.[/red]"
        )
        _record(
            "add_department",
            target_alias=alias,
            result="failure",
            detail=f"partial-env: {specified}",
        )
        raise typer.Exit(code=1)

    use_oauth = len(specified) == 3

    if use_oauth:
        # ADV-US3-14: env names MUST match agenix prefix patterns.
        env_pattern_violations = []
        for field, value in (
            ("channel_id_env", channel_id_env),
            ("client_secret_env", client_secret_env),
            ("api_key_env", api_key_env),
        ):
            if value is not None and not _ENV_NAME_PATTERNS[field].fullmatch(value):
                env_pattern_violations.append((field, value))
        if env_pattern_violations:
            first_field, first_value = env_pattern_violations[0]
            err_console.print(
                f"[red]환경변수명 형식이 올바르지 않습니다 "
                f"({first_field}={first_value}). "
                f"agenix 시크릿 매핑 패턴(TUBE_SCOUT_*)을 확인하세요.[/red]"
            )
            _record(
                "add_department",
                target_alias=alias,
                result="failure",
                detail=f"env-pattern: {first_field}={first_value}",
            )
            raise typer.Exit(code=1)

        missing = _check_envs_present(channel_id_env, client_secret_env, api_key_env)
        if missing:
            err_console.print(
                f"[red]환경변수 {missing[0]}가 정의되어 있지 않습니다. "
                f"agenix 시크릿 등록을 먼저 완료하세요.[/red]"
            )
            _record(
                "add_department",
                target_alias=alias,
                result="failure",
                detail=f"missing env: {missing[0]}",
            )
            raise typer.Exit(code=1)

    # FR-016: cross-registry duplicate check (channels.json)
    try:
        channels_registry = load_registry()
    except Exception:
        channels_registry = {}
    if alias in channels_registry:
        err_console.print(
            f"[red]Alias '{alias}' already registered in channels.json "
            f"with channel_id={channels_registry[alias].channel_id!r}. "
            f"Resolve manually.[/red]"
        )
        _record(
            "add_department",
            target_alias=alias,
            result="failure",
            detail="cross-registry duplicate",
        )
        raise typer.Exit(code=1)

    repo = DepartmentsRepo()
    try:
        repo.add(
            {
                "alias": alias,
                "display_name": display,
                "channel_id_env": channel_id_env,
                "client_secret_env": client_secret_env,
                "api_key_env": api_key_env,
                "registered_at": datetime.now(UTC).isoformat(),
            }
        )
    except DuplicateAliasError:
        err_console.print(f"[red]이미 등록된 학과 alias입니다: {alias}[/red]")
        _record(
            "add_department",
            target_alias=alias,
            result="failure",
            detail="duplicate alias",
        )
        raise typer.Exit(code=1)
    except ValidationError as exc:
        err_console.print(
            "[red]학과 입력값이 올바르지 않습니다 (alias 또는 display 형식 확인).[/red]"
        )
        LOGGER.exception("validation failure: %s", exc)
        _record(
            "add_department", target_alias=alias, result="failure", detail="validation"
        )
        raise typer.Exit(code=1)

    if use_oauth and not no_oauth_consent:
        try:
            _run_oauth_consent(alias)
            _record("oauth_consent", target_alias=alias, result="success")
        except Exception as exc:
            err_console.print(f"[red]OAuth 동의 실패: {exc}[/red]")
            _record(
                "oauth_consent", target_alias=alias, result="failure", detail=str(exc)
            )
            raise typer.Exit(code=1)

    _record("add_department", target_alias=alias, result="success")
    console.print(f"[green]✓ 학과 등록 완료: {alias} ({display})[/green]")


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------


def _build_union_rows() -> list[dict[str, str | None]]:
    """Build union of channels.json + departments.json with source/consistency.

    Returns:
        List of dicts with keys: alias, display_name, channel_id, source,
        consistency. Emits WARNING to stderr for each mismatch alias.
    """
    from tube_scout.services.auth import load_registry
    from tube_scout.web.repo.departments_repo import DepartmentsRepo

    try:
        channels = load_registry()
    except Exception:
        channels = {}
    depts = {d.alias: d for d in DepartmentsRepo().list_all()}

    all_aliases = sorted(set(channels) | set(depts))
    rows = []
    for a in all_aliases:
        in_channels = a in channels
        in_depts = a in depts

        if in_channels and in_depts:
            source = "both"
            dept = depts[a]
            display_name = dept.display_name
            ch_channel_id = channels[a].channel_id
            # Resolve dept channel_id via env var
            dept_channel_id = (
                os.environ.get(dept.channel_id_env)
                if dept.channel_id_env
                else None
            )
            if dept_channel_id and ch_channel_id and dept_channel_id == ch_channel_id:
                consistency = "ok"
            elif dept.channel_id_env is None:
                consistency = "ok"
            else:
                consistency = "mismatch"
            channel_id = ch_channel_id
        elif in_channels:
            source = "channels"
            display_name = channels[a].channel_name
            channel_id = channels[a].channel_id
            consistency = "ok"
        else:
            source = "departments"
            dept = depts[a]
            display_name = dept.display_name
            channel_id = (
                os.environ.get(dept.channel_id_env) if dept.channel_id_env else None
            )
            consistency = "ok"

        if consistency == "mismatch":
            dept = depts[a]
            dept_id = (
                os.environ.get(dept.channel_id_env) if dept.channel_id_env else None
            )
            err_console.print(
                f"WARNING: alias '{a}' mismatch "
                f"(channels.json={channels[a].channel_id}, "
                f"departments.json={dept_id})",
                highlight=False,
            )

        rows.append({
            "alias": a,
            "display_name": display_name,
            "channel_id": channel_id,
            "source": source,
            "consistency": consistency,
        })
    return rows


@admin_app.command("list")
def list_departments(
    json_output: bool = typer.Option(False, "--json", help="JSON 출력"),
) -> None:
    """등록된 학과 목록을 출력한다 (FR-014: channels.json + departments.json union).

    Args:
        json_output: Emit raw JSON instead of a rich table when True.

    Raises:
        typer.Exit: Never raised; exits 0 on empty list.
    """
    rows = _build_union_rows()
    if json_output:
        console.print(json.dumps(rows, ensure_ascii=False))
        return
    if not rows:
        console.print("등록된 학과가 없습니다.")
        return
    table = Table(title="등록된 학과")
    table.add_column("alias")
    table.add_column("display_name")
    table.add_column("channel_id")
    table.add_column("source")
    table.add_column("consistency")
    for r in rows:
        table.add_row(
            r["alias"],
            r["display_name"] or "",
            r["channel_id"] or "—",
            r["source"],
            r["consistency"],
        )
    console.print(table)


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


def _build_status_rows(filter_alias: str | None) -> list[dict[str, Any]]:
    from tube_scout.web.repo import jobs_repo
    from tube_scout.web.repo.departments_repo import DepartmentsRepo

    depts = DepartmentsRepo().list_all()
    if filter_alias is not None:
        depts = [d for d in depts if d.alias == filter_alias]
    job_repo = jobs_repo.JobsRepo()
    rows = []
    for d in depts:
        token = _read_token(d.alias)
        token_status, days = _expiry_status(token)
        running = job_repo.find_in_progress_for_department(d.alias)
        rows.append(
            {
                "alias": d.alias,
                "display_name": d.display_name,
                "token_status": token_status,
                "days_remaining": days,
                "running_jobs": len(running),
            }
        )
    return rows


def _write_status_log_line(rows: list[dict[str, Any]]) -> None:
    """Spec FR-026 / Q3: structured JSON log line on every status check."""
    from tube_scout.web.paths import get_log_dir

    log_path = get_log_dir() / "admin-status.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as fh:
        for row in rows:
            if row["token_status"] in {"expired", "near_expiry"}:
                fh.write(
                    json.dumps(
                        {
                            "ts": datetime.now(UTC).isoformat(),
                            "alias": row["alias"],
                            "token_status": row["token_status"],
                            "days_remaining": row["days_remaining"],
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )


@admin_app.command("status")
def status(
    alias: str | None = typer.Option(None, "--alias", help="특정 학과만 조회"),
    json_output: bool = typer.Option(False, "--json", help="JSON 출력"),
) -> None:
    """OAuth 토큰 상태 + 진행 중 작업 + 최근 7일 운영 동작 요약."""
    rows = _build_status_rows(alias)
    _write_status_log_line(rows)

    if json_output:
        console.print(json.dumps(rows, ensure_ascii=False))
    else:
        if not rows:
            console.print("등록된 학과가 없습니다.")
        else:
            for row in rows:
                if row["token_status"] == "expired":
                    color = "red"
                    label = f"[{color}]✗ {row['alias']:<12} 만료됨[/{color}]"
                elif row["token_status"] == "near_expiry":
                    color = "yellow"
                    label = (
                        f"[{color}]⚠ {row['alias']:<12} 만료 임박 "
                        f"({row['days_remaining']}일 남음)[/{color}]"
                    )
                elif row["token_status"] == "valid":
                    color = "green"
                    label = (
                        f"[{color}]✓ {row['alias']:<12} 유효 "
                        f"(만료까지 {row['days_remaining']}일)[/{color}]"
                    )
                else:
                    label = f"? {row['alias']:<12} 토큰 없음"
                console.print(label)
                if row["running_jobs"]:
                    console.print(
                        f"   진행 중 작업: {row['running_jobs']}건 "
                        f"({row['alias']}, running)"
                    )

    _record(
        "status_check",
        target_alias=alias,
        result="success",
        detail=f"rows={len(rows)}",
    )


# ---------------------------------------------------------------------------
# refresh
# ---------------------------------------------------------------------------


@admin_app.command("refresh")
def refresh(
    alias: str = typer.Argument(..., help="학과 alias"),
    force: bool = typer.Option(False, "--force", help="만료 임박 여부 무시"),
) -> None:
    """OAuth 토큰을 강제 갱신한다."""
    from tube_scout.web.repo.departments_repo import DepartmentsRepo

    dept = DepartmentsRepo().find_by_alias(alias)
    if dept is None:
        err_console.print(f"[red]등록되지 않은 학과 alias입니다: {alias}[/red]")
        _record(
            "token_refresh",
            target_alias=alias,
            result="failure",
            detail="unknown alias",
        )
        raise typer.Exit(code=1)

    token = _read_token(alias)
    token_status, _ = _expiry_status(token)

    if not force and token_status == "valid":
        console.print(f"토큰이 유효합니다. 갱신을 건너뜁니다: {alias}")
        _record(
            "token_refresh",
            target_alias=alias,
            result="success",
            detail="skipped (valid)",
        )
        return

    try:
        _refresh_token(alias)
    except Exception as exc:
        err_console.print(f"[red]토큰 갱신 실패: {exc}[/red]")
        _record("token_refresh", target_alias=alias, result="failure", detail=str(exc))
        raise typer.Exit(code=1)

    _record("token_refresh", target_alias=alias, result="success")
    console.print(f"[green]✓ 토큰 갱신 완료: {alias}[/green]")


# ---------------------------------------------------------------------------
# verify
# ---------------------------------------------------------------------------


@admin_app.command("verify")
def verify(alias: str = typer.Argument(..., help="학과 alias")) -> None:
    """6단계 health check (env 3종 + 토큰 + access token + API 호출)."""
    from tube_scout.web.repo.departments_repo import DepartmentsRepo

    dept = DepartmentsRepo().find_by_alias(alias)
    if dept is None:
        err_console.print(f"[red]등록되지 않은 학과 alias입니다: {alias}[/red]")
        _record("verify", target_alias=alias, result="failure", detail="unknown alias")
        raise typer.Exit(code=1)

    console.print(f"verify: {alias} ({dept.display_name})")

    missing = _check_envs_present(
        dept.channel_id_env, dept.client_secret_env, dept.api_key_env
    )
    if missing:
        err_console.print(
            f"[red][✗] 환경변수 {missing[0]}가 정의되어 있지 않습니다.[/red]"
        )
        _record(
            "verify",
            target_alias=alias,
            result="failure",
            detail=f"missing env: {missing[0]}",
        )
        raise typer.Exit(code=1)
    console.print("  [green][✓] 환경변수 채널 ID[/green]")
    console.print("  [green][✓] 환경변수 클라이언트 시크릿[/green]")
    console.print("  [green][✓] 환경변수 API 키[/green]")

    token = _read_token(alias)
    if token is None:
        err_console.print("[red][✗] 토큰 파일 없음[/red]")
        _record("verify", target_alias=alias, result="failure", detail="missing token")
        raise typer.Exit(code=1)
    console.print("  [green][✓] 토큰 파일 존재[/green]")

    token_status, _ = _expiry_status(token)
    if token_status != "valid" and token_status != "near_expiry":
        err_console.print(f"[red][✗] access token 무효 ({token_status})[/red]")
        _record(
            "verify",
            target_alias=alias,
            result="failure",
            detail=f"token={token_status}",
        )
        raise typer.Exit(code=1)
    console.print("  [green][✓] access token 유효[/green]")

    channel_id = os.environ.get(dept.channel_id_env, "")
    try:
        info = _youtube_api_probe(alias, channel_id)
    except Exception as exc:
        err_msg = str(exc)
        if "quota" in err_msg.lower():
            err_console.print(
                "[red][✗] API 일일 할당량을 초과했습니다. 내일 다시 시도하세요.[/red]"
            )
        else:
            err_console.print(f"[red][✗] YouTube API 호출 실패: {exc}[/red]")
        _record("verify", target_alias=alias, result="failure", detail=err_msg)
        raise typer.Exit(code=1)

    channel_name = info.get("channel_name", "unknown")
    console.print(
        f"  [green][✓] YouTube API 호출 성공 (채널: {channel_name})[/green]"
    )
    console.print("[green]완료. 이 학과는 분석에 사용할 준비가 되었습니다.[/green]")
    _record("verify", target_alias=alias, result="success")
