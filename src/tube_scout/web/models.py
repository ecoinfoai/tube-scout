"""Pydantic v2 models for the admin web UI (T020).

Mirrors the entities defined in ``specs/008-admin-web-ui/data-model.md``:

- :class:`Department` — operator-managed mapping of alias → display name and
  agenix env-var names.
- :class:`AnalysisJob` — single analysis run with state-machine fields.
- :class:`AnalysisResult` — completed-job artifact paths + summary counts.
- :class:`ReviewStatus` — reuse-detection pair review (spec 007 integration).
- :class:`OperatorAction` — append-only audit log row.
- :class:`SessionPayload` — itsdangerous-signed cookie payload.
- :class:`LoginAttempt` — in-memory rate-limit tracker entry.

Constitution II (Fail-Fast): every model validates inputs at construction;
no silent coercion of missing required fields.
Constitution III (Type Safety): every field is typed; Annotated constraints
mirror the SQLite CHECK and JSON-schema rules.
Constitution VI (Secrets): no model carries plaintext secrets — only env-var
*names*.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints


# ---------------------------------------------------------------------------
# 1. Department
# ---------------------------------------------------------------------------

AliasStr = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9-]{0,31}$")]
DisplayNameStr = Annotated[str, StringConstraints(min_length=1, max_length=32)]
ChannelIdEnvStr = Annotated[
    str, StringConstraints(pattern=r"^TUBE_SCOUT_CHANNEL_ID_[A-Z0-9_]+$")
]
ClientSecretEnvStr = Annotated[
    str, StringConstraints(pattern=r"^TUBE_SCOUT_CLIENT_SECRET_[A-Z0-9_]+$")
]
ApiKeyEnvStr = Annotated[
    str, StringConstraints(pattern=r"^TUBE_SCOUT_API_KEY_[A-Z0-9_]+$")
]


class Department(BaseModel):
    """Per-department analysis credentials mapping.

    Field details mirror data-model.md §1. The model carries env-var *names*
    only — the actual secrets live in agenix and are read at runtime.
    """

    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    alias: AliasStr
    display_name: DisplayNameStr
    channel_id_env: ChannelIdEnvStr
    client_secret_env: ClientSecretEnvStr
    api_key_env: ApiKeyEnvStr
    registered_at: AwareDatetime
    last_used_at: AwareDatetime | None = None


# ---------------------------------------------------------------------------
# 2. AnalysisJob
# ---------------------------------------------------------------------------

JobIdStr = Annotated[str, StringConstraints(pattern=r"^\d{8}-\d{6}(-\d+)?$")]
ProfessorNameStr = Annotated[str, StringConstraints(min_length=1, max_length=32)]
CourseNameStr = Annotated[str, StringConstraints(min_length=1, max_length=64)]

JobStatus = Literal["pending", "running", "completed", "failed", "interrupted"]
JobStage = Literal[
    "listing",
    "metadata",
    "transcripts",
    "retention",
    "analytics",
    "reuse_detection",
    "reporting",
    "done",
]

# Monotonic order index for stage transition validation (used by jobs_repo).
STAGE_ORDER: dict[str, int] = {
    "listing": 1,
    "metadata": 2,
    "transcripts": 3,
    "retention": 4,
    "analytics": 5,
    "reuse_detection": 6,
    "reporting": 7,
    "done": 8,
}


class AnalysisJob(BaseModel):
    """Single analysis run (form submission → background pipeline)."""

    model_config = ConfigDict(str_strip_whitespace=True)

    job_id: JobIdStr
    department_alias: AliasStr
    professor_name: ProfessorNameStr
    course_name: CourseNameStr
    period_start: date
    period_end: date
    status: JobStatus
    current_stage: JobStage | None = None
    processed_count: Annotated[int, Field(ge=0)] = 0
    total_count: Annotated[int, Field(ge=0)] = 0
    result_dir: str | None = None
    started_at: datetime
    completed_at: datetime | None = None
    error_code: str | None = None
    error_detail: str | None = None
    created_by: Annotated[str, StringConstraints(min_length=1)]


# ---------------------------------------------------------------------------
# 3. AnalysisResult
# ---------------------------------------------------------------------------


class PrioritySummary(BaseModel):
    """Counts of reuse-detection pair priorities (spec 007)."""

    model_config = ConfigDict(frozen=True)

    critical: Annotated[int, Field(ge=0)]
    high: Annotated[int, Field(ge=0)]
    moderate: Annotated[int, Field(ge=0)]
    normal: Annotated[int, Field(ge=0)]


class AnalysisResult(BaseModel):
    """Completed job artifact paths + summary counts."""

    model_config = ConfigDict(str_strip_whitespace=True)

    job_id: JobIdStr
    report_v1v3_html: str | None = None
    report_v1v3_pdf: str | None = None
    report_v1v3_excel: str | None = None
    report_reuse_html: str | None = None
    report_reuse_excel: str | None = None
    matched_video_count: Annotated[int, Field(ge=0)] = 0
    suspicious_pair_count: Annotated[int, Field(ge=0)] = 0
    priority_summary: PrioritySummary
    generated_at: datetime


# ---------------------------------------------------------------------------
# 4. ReviewStatus
# ---------------------------------------------------------------------------

ReviewStatusValue = Literal["unreviewed", "confirmed_duplicate", "false_positive"]


class ReviewStatus(BaseModel):
    """Reviewer state for a reuse-detection pair (spec 007 integration)."""

    model_config = ConfigDict(str_strip_whitespace=True)

    pair_id: Annotated[str, StringConstraints(min_length=1)]
    job_id: JobIdStr
    status: ReviewStatusValue = "unreviewed"
    updated_at: datetime | None = None
    updated_by: str | None = None
    note: Annotated[str, StringConstraints(max_length=512)] | None = None


# ---------------------------------------------------------------------------
# 5. OperatorAction
# ---------------------------------------------------------------------------

OperatorActionType = Literal[
    "add_department",
    "oauth_consent",
    "token_refresh",
    "status_check",
    "verify",
]
OperatorActionResult = Literal["success", "failure"]


class OperatorAction(BaseModel):
    """Append-only audit log row for operator CLI actions."""

    model_config = ConfigDict(str_strip_whitespace=True)

    id: int | None = None  # autoincremented by SQLite
    action: OperatorActionType
    target_alias: AliasStr | None = None
    actor: Annotated[str, StringConstraints(min_length=1)]
    at: datetime
    result: OperatorActionResult
    detail: str | None = None


# ---------------------------------------------------------------------------
# 6. SessionPayload (itsdangerous cookie)
# ---------------------------------------------------------------------------


class SessionPayload(BaseModel):
    """Cookie payload signed by itsdangerous; never stored server-side."""

    model_config = ConfigDict(frozen=True)

    username: Annotated[str, StringConstraints(min_length=1, max_length=128)]
    issued_at: Annotated[int, Field(ge=0)]
    last_active: Annotated[int, Field(ge=0)]
    csrf_token: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{32}$")]


# ---------------------------------------------------------------------------
# 7. LoginAttempt (in-memory)
# ---------------------------------------------------------------------------


class LoginAttempt(BaseModel):
    """In-memory rate-limit tracker entry (data-model.md §7)."""

    model_config = ConfigDict()

    fail_count: Annotated[int, Field(ge=0, le=10)] = 0
    locked_until: datetime | None = None
    last_failure_at: datetime | None = None
