"""Korean user-facing error messages (T032).

Per spec FR-015 + http-routes.md cross-cutting: every internal error code
maps to a single Korean user message; English log detail stays in stdout /
journald and never reaches the HTTP body.

Adding a new error code requires:
1. Adding a row here.
2. Adding the code to the contract test catalogue (T015).
3. Verifying the message contains no env-var names, paths, tokens, or
   stack-frame identifiers (Constitution VI / spec SC-006).
"""

from __future__ import annotations

USER_MESSAGES: dict[str, str] = {
    # auth.* (login form + session lifecycle)
    "auth.bad_credentials": "아이디 또는 비밀번호가 올바르지 않습니다.",
    "auth.locked": "로그인이 잠겼습니다. {seconds}초 후 다시 시도하세요.",
    "auth.csrf": "보안 토큰이 만료되었습니다. 새로고침 후 다시 시도하세요.",
    # form.* (POST /jobs validation)
    "form.department_unknown": "선택한 학과를 찾을 수 없습니다.",
    "form.professor_invalid": "교수명을 올바르게 입력하세요.",
    "form.course_invalid": "과목명을 올바르게 입력하세요.",
    "form.period_inverted": "시작일은 종료일 이전이어야 합니다.",
    "form.period_future": "시작일은 미래일 수 없습니다.",
    "form.same_department_running": (
        "동일 학과 분석이 이미 진행 중입니다 — 잠시 후 다시 시도하세요."
    ),
    # pipeline.* (background job failures)
    "pipeline.oauth_expired": (
        "인증이 만료되었습니다. 운영자에게 토큰 갱신을 요청하세요."
    ),
    "pipeline.quota_exceeded": (
        "API 일일 할당량을 초과했습니다. 내일 다시 시도하거나 운영자에게 문의하세요."
    ),
    "pipeline.no_videos": "조건에 맞는 영상이 없습니다.",
    "pipeline.internal": "분석 중 내부 오류가 발생했습니다 — 운영자에게 문의하세요.",
    # files.* (GET /jobs/{id}/files/{kind})
    "files.missing": "파일을 찾을 수 없습니다 — 재실행이 필요합니다.",
    "files.unknown_kind": "요청한 파일 형식을 처리할 수 없습니다.",
    "files.traversal": "잘못된 파일 경로 요청입니다.",
    # session.*
    "session.expired": "세션이 만료되었습니다. 다시 로그인하세요.",
    "session.invalid": "세션이 올바르지 않습니다. 다시 로그인하세요.",
    # retry.*
    "retry.invalid_state": "재실행할 수 없는 상태입니다.",
    # review.*
    "review.invalid_status": "리뷰 상태 값이 올바르지 않습니다.",
    "review.note_too_long": "리뷰 메모는 512자 이하여야 합니다.",
}

FALLBACK_MESSAGE: str = "내부 오류가 발생했습니다 — 운영자에게 문의하세요."


def to_user_message(code: str, **context: object) -> str:
    """Return the Korean user-facing message for ``code``.

    Args:
        code: Internal error code (e.g. ``auth.locked``).
        **context: String-format substitutions (e.g. ``seconds=120`` for
            ``auth.locked``).

    Returns:
        Korean message with substitutions applied. Unknown codes return the
        fallback message; format-string failures fall back to the unformatted
        template (rather than raising and leaking the unmapped key).

    Raises:
        ValueError: If ``code`` is empty (Constitution II Fail-Fast).
    """
    if not code:
        raise ValueError("code must be a non-empty string")
    template = USER_MESSAGES.get(code, FALLBACK_MESSAGE)
    if not context:
        return template
    try:
        return template.format(**context)
    except (KeyError, IndexError):
        # intentional-skip: substitution missing → return raw template so the
        # user still sees a Korean message instead of a 500 with a KeyError
        # leaking the missing key name.
        return template
