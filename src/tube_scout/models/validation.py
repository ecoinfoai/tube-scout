"""Validation finding model."""

import re
from typing import Any

from pydantic import BaseModel, Field, field_validator

VALID_SEVERITIES = frozenset({"ERROR", "WARNING", "INFO"})
VALID_RULE_PATTERN = re.compile(r"^V-00[1-9]$")


class ValidationFinding(BaseModel):
    """A detected anomaly from title validation.

    Args:
        rule_id: Validation rule identifier (V-001 to V-009).
        severity: Severity level (ERROR, WARNING, INFO).
        video_ids: List of affected video IDs (non-empty).
        professor: Affected professor name if applicable.
        description: Human-readable finding description in English.
        details: Rule-specific details (e.g., expected vs actual values).
    """

    rule_id: str
    severity: str
    video_ids: list[str] = Field(..., min_length=1)
    professor: str | None = None
    description: str = Field(..., min_length=1)
    details: dict[str, Any] = Field(default_factory=dict)

    @field_validator("rule_id")
    @classmethod
    def rule_id_must_be_valid(cls, v: str) -> str:
        """Validate that rule_id matches V-001 to V-009 format."""
        if not VALID_RULE_PATTERN.match(v):
            raise ValueError("rule_id must be V-001 to V-009")
        return v

    @field_validator("severity")
    @classmethod
    def severity_must_be_valid(cls, v: str) -> str:
        """Validate that severity is ERROR, WARNING, or INFO."""
        if v not in VALID_SEVERITIES:
            raise ValueError(f"severity must be one of {sorted(VALID_SEVERITIES)}")
        return v

    @field_validator("description")
    @classmethod
    def description_must_not_be_blank(cls, v: str) -> str:
        """Validate that description is not blank."""
        if not v.strip():
            raise ValueError("description must not be blank")
        return v
