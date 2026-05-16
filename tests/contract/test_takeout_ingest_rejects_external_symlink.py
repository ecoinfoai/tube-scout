"""Contract: takeout_ingest must reject mp4 symlinks that resolve outside takeout_dir.

T-04 latent critical — abs_path.resolve() follows symlink chains, so a symlink in
the Takeout archive's video dir that points outside takeout_dir could appear in
mp4_video_id_map and later be unlinked by source_video_cleanup.

This contract test verifies that ingest_takeout raises ValueError when a symlink
in the archive's 동영상/ directory resolves to a path outside takeout_dir.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


_ALIAS = "pharmacy_test"
_CHANNEL_ID = "UCfakeSymlinkTest0000000"
_VID = "vid0001ExtTest"


def _make_takeout_with_external_symlink(tmp_path: Path) -> tuple[Path, Path]:
    """Create a minimal Takeout archive where one mp4 is a symlink pointing outside."""
    takeout_dir = tmp_path / "Takeout"
    video_dir = takeout_dir / "YouTube 및 YouTube Music" / "동영상"
    video_dir.mkdir(parents=True, exist_ok=True)
    meta_dir = takeout_dir / "YouTube 및 YouTube Music" / "동영상 메타데이터"
    meta_dir.mkdir(parents=True, exist_ok=True)
    channel_dir = takeout_dir / "YouTube 및 YouTube Music" / "채널"
    channel_dir.mkdir(parents=True, exist_ok=True)

    # Create a real mp4 outside the archive (simulates attacker-controlled file)
    external_dir = tmp_path / "outside_archive"
    external_dir.mkdir(parents=True, exist_ok=True)
    external_mp4 = external_dir / f"{_VID}.mp4"
    external_mp4.write_bytes(b"\x00" * 512)

    # Create symlink inside archive pointing outside
    symlink_mp4 = video_dir / f"{_VID}.mp4"
    symlink_mp4.symlink_to(external_mp4)

    (meta_dir / "동영상.csv").write_text(
        "동영상 ID,동영상 제목(원본),근사치 길이(밀리초),채널 ID,개인 정보 보호,"
        "동영상 생성 타임스탬프\n"
        f"{_VID},테스트 영상 0,60000,{_CHANNEL_ID},공개,2024-01-01T00:00:00Z\n",
        encoding="utf-8",
    )
    (channel_dir / "채널.csv").write_text(
        f"채널 ID,채널 제목(원본)\n{_CHANNEL_ID},{_ALIAS}\n",
        encoding="utf-8",
    )

    return takeout_dir, external_mp4


def test_ingest_rejects_external_symlink(tmp_path: Path) -> None:
    """mp4_video_id_map must not contain paths that resolve outside takeout_dir."""
    from tube_scout.services.takeout_ingest import ingest_takeout

    takeout_dir, _external_mp4 = _make_takeout_with_external_symlink(tmp_path)
    work_root = tmp_path / "work"
    db_path = tmp_path / "test.db"

    mock_reg = MagicMock()
    mock_reg.channel_id = _CHANNEL_ID

    with patch(
        "tube_scout.services.takeout_ingest._load_alias_registry",
        return_value={_ALIAS: mock_reg},
    ):
        with pytest.raises(ValueError, match="outside.*takeout|containment|symlink|external"):
            ingest_takeout(
                takeout_dir=takeout_dir,
                channel_alias=_ALIAS,
                db_path=db_path,
                work_root=work_root,
            )
