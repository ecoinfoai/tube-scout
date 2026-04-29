"""Tests for tube_scout.web.errors (T015 RED).

Covers:
- Every internal error code maps to a Korean user message
- Fallback message exists for unknown codes
- to_user_message accepts context kwargs (e.g. ``seconds=120``) and embeds
  them into the message
- No message contains environment variable names, file paths, stack frame
  identifiers, or token strings (spec SC-006)

Targets ``tube_scout.web.errors`` — implementation pending (T032).
"""

from __future__ import annotations

import re

import pytest

# Per http-routes.md and spec FR-007/FR-018/FR-026, every code referenced
# anywhere in the contracts must have a Korean message.
REQUIRED_CODES = [
    "auth.bad_credentials",
    "auth.locked",
    "auth.csrf",
    "form.department_unknown",
    "form.professor_invalid",
    "form.course_invalid",
    "form.period_inverted",
    "form.period_future",
    "form.same_department_running",
    "pipeline.oauth_expired",
    "pipeline.quota_exceeded",
    "pipeline.no_videos",
    "pipeline.internal",
    "files.missing",
    "files.unknown_kind",
    "files.traversal",
    "session.expired",
    "session.invalid",
    "retry.invalid_state",
    "review.invalid_status",
    "review.note_too_long",
]

LEAK_PATTERNS = [
    re.compile(r"TUBE_SCOUT_[A-Z_]+"),
    re.compile(r"~/\.config/tube-scout"),
    re.compile(r"~/\.local/share"),
    re.compile(r"agenix"),
    re.compile(r"ya29\.[A-Za-z0-9._-]+"),
    re.compile(r"1//[A-Za-z0-9_-]+"),
    re.compile(r"/home/[^\s\"]+"),
    re.compile(r"Traceback"),
    re.compile(r"\.py:\d+"),
]


def test_every_required_code_has_kr_message() -> None:
    from tube_scout.web import errors

    for code in REQUIRED_CODES:
        msg = errors.to_user_message(code)
        assert msg, f"empty message for code: {code}"
        # Each message contains at least one Hangul block character.
        assert re.search(r"[가-힣]", msg), (
            f"no Korean chars in message for {code}: {msg!r}"
        )


def test_unknown_code_falls_back_to_internal_message() -> None:
    from tube_scout.web import errors

    msg = errors.to_user_message("definitely.not.a.real.code")
    assert "내부 오류" in msg or "운영자" in msg


def test_context_substitution() -> None:
    from tube_scout.web import errors

    # auth.locked has ``{seconds}`` interpolation.
    msg = errors.to_user_message("auth.locked", seconds=120)
    assert "120" in msg


def test_no_secret_or_path_leaks_in_any_message() -> None:
    from tube_scout.web import errors

    for code in REQUIRED_CODES:
        msg = errors.to_user_message(code)
        for pattern in LEAK_PATTERNS:
            assert pattern.search(msg) is None, (
                f"leak pattern {pattern.pattern!r} found in {code} message: {msg!r}"
            )


def test_to_user_message_rejects_empty_code() -> None:
    from tube_scout.web import errors

    with pytest.raises(ValueError):
        errors.to_user_message("")


def test_pipeline_not_integrated_unreachable_after_t035bis() -> None:
    """R-9: ``pipeline.not_integrated`` is removed once the helper is wired.

    The code existed only while T035 stub raised it. After T035-bis,
    ``cli.collect._collect_all_for_web`` is the integration point and
    nothing emits this code. Asserting absence prevents the dead row from
    being re-added by accident.
    """
    from tube_scout.web import errors

    assert "pipeline.not_integrated" not in errors.USER_MESSAGES
    # Calling with the now-unmapped code falls back to the internal message.
    fallback = errors.to_user_message("pipeline.not_integrated")
    assert "내부 오류" in fallback or "운영자" in fallback
