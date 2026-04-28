"""Tests for tube_scout.web.repo.operator_actions_repo (T011 RED).

Covers:
- record_action append-only insert
- ``at`` DESC ordering on retrieval
- action enum CHECK rejection
- result enum CHECK rejection
- recent-window query helper

Targets ``tube_scout.web.repo.operator_actions_repo`` — implementation
pending (T026).
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import pytest


@pytest.fixture
def state_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setenv("TUBE_SCOUT_STATE_DIR", str(tmp_path))
    return tmp_path


def test_record_action_inserts_row(state_dir: Path) -> None:
    from tube_scout.web.repo import db, operator_actions_repo

    db.bootstrap()
    repo = operator_actions_repo.OperatorActionsRepo()
    repo.record_action(
        action="add_department",
        target_alias="physiology",
        actor="kjeong",
        result="success",
        detail=None,
    )
    rows = repo.list_recent(limit=10)
    assert len(rows) == 1
    assert rows[0].action == "add_department"
    assert rows[0].result == "success"


def test_recent_returns_at_desc_order(state_dir: Path) -> None:
    from tube_scout.web.repo import db, operator_actions_repo

    db.bootstrap()
    repo = operator_actions_repo.OperatorActionsRepo()
    repo.record_action(
        action="status_check",
        target_alias=None,
        actor="kjeong",
        result="success",
        detail=None,
    )
    time.sleep(0.01)
    repo.record_action(
        action="token_refresh",
        target_alias="physiology",
        actor="kjeong",
        result="success",
        detail=None,
    )
    time.sleep(0.01)
    repo.record_action(
        action="verify",
        target_alias="physiology",
        actor="kjeong",
        result="failure",
        detail="step 5 failed",
    )
    rows = repo.list_recent(limit=10)
    assert [r.action for r in rows] == ["verify", "token_refresh", "status_check"]


def test_unknown_action_rejected(state_dir: Path) -> None:
    from tube_scout.web.repo import db, operator_actions_repo

    db.bootstrap()
    repo = operator_actions_repo.OperatorActionsRepo()
    with pytest.raises(sqlite3.IntegrityError):
        repo.record_action(
            action="exploded",
            target_alias=None,
            actor="kjeong",
            result="success",
            detail=None,
        )


def test_unknown_result_rejected(state_dir: Path) -> None:
    from tube_scout.web.repo import db, operator_actions_repo

    db.bootstrap()
    repo = operator_actions_repo.OperatorActionsRepo()
    with pytest.raises(sqlite3.IntegrityError):
        repo.record_action(
            action="status_check",
            target_alias=None,
            actor="kjeong",
            result="maybe",
            detail=None,
        )


def test_list_recent_with_limit(state_dir: Path) -> None:
    from tube_scout.web.repo import db, operator_actions_repo

    db.bootstrap()
    repo = operator_actions_repo.OperatorActionsRepo()
    for _ in range(5):
        repo.record_action(
            action="status_check",
            target_alias=None,
            actor="kjeong",
            result="success",
            detail=None,
        )
        time.sleep(0.005)
    rows = repo.list_recent(limit=3)
    assert len(rows) == 3
