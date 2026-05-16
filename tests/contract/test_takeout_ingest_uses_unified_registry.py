"""Contract: ingest_takeout must reject alias absent from all registries (union check).

T-17 residual — B-9 union logic lives in cli/collect.py but not in the service
layer. ingest_takeout must itself fail when the alias is registered in neither
channels.json nor departments.json, regardless of CLI invocation.

This contract tests the service layer directly (no CLI), confirming that an alias
registered in only one registry (or neither) is handled correctly:
- alias in neither registry → ValueError (unregistered)
- alias in channels registry only → allowed (single-registry alias is valid)
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


_ALIAS_UNREGISTERED = "ghost_alias_xyz"
_ALIAS_CHANNELS_ONLY = "channels_only_alias"
_CHANNEL_ID = "UCfakeRegistryTest000000"
_VID = "vid0001RegTest"


def _make_minimal_takeout(tmp_path: Path, alias: str) -> Path:
    """Create a minimal Takeout archive with one video for the given alias."""
    takeout_dir = tmp_path / "Takeout"
    video_dir = takeout_dir / "YouTube 및 YouTube Music" / "동영상"
    video_dir.mkdir(parents=True, exist_ok=True)
    meta_dir = takeout_dir / "YouTube 및 YouTube Music" / "동영상 메타데이터"
    meta_dir.mkdir(parents=True, exist_ok=True)
    channel_dir = takeout_dir / "YouTube 및 YouTube Music" / "채널"
    channel_dir.mkdir(parents=True, exist_ok=True)

    (video_dir / f"{_VID}.mp4").write_bytes(b"\x00" * 512)

    (meta_dir / "동영상.csv").write_text(
        "동영상 ID,동영상 제목(원본),근사치 길이(밀리초),채널 ID,개인 정보 보호,"
        "동영상 생성 타임스탬프\n"
        f"{_VID},테스트 영상 0,60000,{_CHANNEL_ID},공개,2024-01-01T00:00:00Z\n",
        encoding="utf-8",
    )
    (channel_dir / "채널.csv").write_text(
        f"채널 ID,채널 제목(원본)\n{_CHANNEL_ID},{alias}\n",
        encoding="utf-8",
    )

    return takeout_dir


def test_ingest_rejects_alias_not_in_any_registry(tmp_path: Path) -> None:
    """ingest_takeout must raise ValueError when alias is absent from all registries."""
    from tube_scout.services.takeout_ingest import ingest_takeout

    takeout_dir = _make_minimal_takeout(tmp_path, _ALIAS_UNREGISTERED)
    work_root = tmp_path / "work"
    db_path = tmp_path / "test.db"

    # Empty registry — alias registered in neither channels.json nor departments.json
    with patch(
        "tube_scout.services.takeout_ingest._load_alias_registry",
        return_value={},
    ):
        with pytest.raises(ValueError, match="not registered|unregistered"):
            ingest_takeout(
                takeout_dir=takeout_dir,
                channel_alias=_ALIAS_UNREGISTERED,
                db_path=db_path,
                work_root=work_root,
            )


def test_ingest_accepts_alias_in_channels_registry(tmp_path: Path) -> None:
    """ingest_takeout must succeed when alias is registered in channels registry."""
    from tube_scout.services.takeout_ingest import ingest_takeout

    takeout_dir = _make_minimal_takeout(tmp_path, _ALIAS_CHANNELS_ONLY)
    work_root = tmp_path / "work"
    db_path = tmp_path / "test.db"

    mock_reg = MagicMock()
    mock_reg.channel_id = _CHANNEL_ID

    # Alias in channels registry only (no departments registry entry)
    with patch(
        "tube_scout.services.takeout_ingest._load_alias_registry",
        return_value={_ALIAS_CHANNELS_ONLY: mock_reg},
    ):
        result = ingest_takeout(
            takeout_dir=takeout_dir,
            channel_alias=_ALIAS_CHANNELS_ONLY,
            db_path=db_path,
            work_root=work_root,
        )

    assert result.channel_alias == _ALIAS_CHANNELS_ONLY
