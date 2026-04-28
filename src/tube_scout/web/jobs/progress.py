"""In-memory job progress dataclass + JSON serializer (T033).

Renders the snapshot exposed by ``GET /jobs/{id}/progress`` per
http-routes.md. The dataclass is the in-memory model used by the runner
(T034) to update progress between pipeline stages; :func:`serialize` produces
the exact JSON shape consumed by the browser polling loop.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


_STAGE_LABELS_KR: dict[str, str] = {
    "listing": "영상 목록 수집 중",
    "metadata": "메타데이터 수집 중",
    "transcripts": "자막 수집 중",
    "retention": "Retention 데이터 수집 중",
    "analytics": "Analytics 데이터 수집 중",
    "reuse_detection": "재사용 탐지 분석 중",
    "reporting": "보고서 생성 중",
    "done": "완료",
}


def stage_label_kr(stage: str) -> str:
    """Return the Korean label for a pipeline stage.

    Args:
        stage: One of the 8 stage names defined in data-model.md.

    Returns:
        Korean label suitable for the progress UI.

    Raises:
        ValueError: If ``stage`` is not a known stage (Constitution II).
    """
    if stage not in _STAGE_LABELS_KR:
        raise ValueError(f"unknown pipeline stage: {stage!r}")
    return _STAGE_LABELS_KR[stage]


@dataclass(frozen=True)
class JobProgress:
    """Snapshot of a job's runtime progress.

    Mirrors the public field set returned by ``GET /jobs/{id}/progress`` —
    intentionally lightweight, the runner constructs new instances on each
    transition rather than mutating shared state.
    """

    job_id: str
    status: str
    current_stage: str | None
    processed_count: int
    total_count: int
    started_at: str
    completed_at: str | None
    error_code: str | None
    error_message_kr: str | None


def serialize(snapshot: JobProgress) -> dict[str, Any]:
    """Return the JSON-serializable payload for a progress snapshot.

    Output shape mirrors http-routes.md GET /progress contract exactly:
        job_id, status, current_stage, stage_label_kr, processed, total,
        started_at, completed_at, error_code, error_message_kr.

    Args:
        snapshot: Progress snapshot to serialize.

    Returns:
        Dict with the contract field set; ``stage_label_kr`` is None when
        ``current_stage`` is None (pending state).
    """
    label = (
        stage_label_kr(snapshot.current_stage)
        if snapshot.current_stage is not None
        else None
    )
    return {
        "job_id": snapshot.job_id,
        "status": snapshot.status,
        "current_stage": snapshot.current_stage,
        "stage_label_kr": label,
        "processed": snapshot.processed_count,
        "total": snapshot.total_count,
        "started_at": snapshot.started_at,
        "completed_at": snapshot.completed_at,
        "error_code": snapshot.error_code,
        "error_message_kr": snapshot.error_message_kr,
    }
