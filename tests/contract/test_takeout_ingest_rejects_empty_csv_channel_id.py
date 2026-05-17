"""Contract: takeout_ingest must raise ValueError when archive CSV channel_id is empty.

e0eb129 fix — csv_channel_id falsy check prevents mismatch validation bypass.
An archive whose 채널.csv has an empty channel_id column must be rejected
before any DB writes occur.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_ALIAS = "nursing_csv_test"
_CHANNEL_ID = "UCfakeCsvEmptyTest000000"
_VID = "vid0001CsvTest"


def _make_takeout_empty_channel_id(tmp_path: Path) -> Path:
    """Create a Takeout archive where 채널.csv has an empty channel_id."""
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
    # Empty channel_id in 채널.csv
    (channel_dir / "채널.csv").write_text(
        f"채널 ID,채널 제목(원본)\n,{_ALIAS}\n",
        encoding="utf-8",
    )

    return takeout_dir


def test_ingest_rejects_empty_csv_channel_id(tmp_path: Path) -> None:
    """ValueError must be raised when archive CSV channel_id is empty string."""
    from tube_scout.services.takeout_ingest import ingest_takeout

    takeout_dir = _make_takeout_empty_channel_id(tmp_path)
    work_root = tmp_path / "work"
    db_path = tmp_path / "test.db"

    mock_reg = MagicMock()
    mock_reg.channel_id = _CHANNEL_ID

    with patch(
        "tube_scout.services.takeout_ingest._load_alias_registry",
        return_value={_ALIAS: mock_reg},
    ):
        with pytest.raises(ValueError, match="empty|missing|channel_id"):
            ingest_takeout(
                takeout_dir=takeout_dir,
                channel_alias=_ALIAS,
                db_path=db_path,
                work_root=work_root,
            )
