"""RED tests for _PRIVACY_MAPPING unknown-value handling — Defect 7 regression (T011).

FR-005, R-4: unknown Korean privacy value (e.g. '예약 공개') must
  - skip the video row (not persist)
  - write audit row: result=skip, reason=unknown_privacy_value, raw_value=<원본>
  - continue processing remaining videos
"""

from __future__ import annotations

import csv
from pathlib import Path
from unittest import mock

import pytest


_REAL_CHANNEL_HEADER = [
    "채널 ID", "채널 국가", "채널 태그 1", "채널 제목(원본)", "채널 공개 상태",
]
_REAL_VIDEO_HEADER = [
    "동영상 ID", "근사치 길이(밀리초)", "동영상 오디오 언어", "동영상 카테고리",
    "동영상 설명(원본) 언어", "채널 ID", "동영상 제목(원본)", "동영상 제목(원본) 언어",
    "개인 정보 보호", "동영상 상태", "동영상 생성 타임스탬프",
]


def _write_channel_csv(path: Path, channel_id: str = "UCtest001") -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(_REAL_CHANNEL_HEADER)
        w.writerow([channel_id, "KR", "태그", "테스트채널", "공개"])


def _video_row(video_id: str, privacy: str = "비공개") -> dict:
    return {
        "동영상 ID": video_id,
        "근사치 길이(밀리초)": "3600000",
        "동영상 오디오 언어": "ko",
        "동영상 카테고리": "교육",
        "동영상 설명(원본) 언어": "ko",
        "채널 ID": "UCtest001",
        "동영상 제목(원본)": f"제목_{video_id}",
        "동영상 제목(원본) 언어": "ko",
        "개인 정보 보호": privacy,
        "동영상 상태": "처리됨",
        "동영상 생성 타임스탬프": "2026-01-01T00:00:00+00:00",
    }


def _make_takeout_tree(tmp_path: Path) -> tuple[Path, Path, Path]:
    yt_dir = tmp_path / "YouTube 및 YouTube Music"
    meta_dir = yt_dir / "동영상 메타데이터"
    channel_dir = yt_dir / "채널"
    meta_dir.mkdir(parents=True)
    channel_dir.mkdir(parents=True)
    return tmp_path, meta_dir, channel_dir


class TestUnknownPrivacyValueHandling:
    """T011 — unknown Korean privacy value skipped with audit row, others processed."""

    def test_unknown_privacy_skipped_other_videos_continue(self, tmp_path: Path) -> None:
        """'예약 공개' row skipped; vid_ok1 and vid_ok2 must still be parsed."""
        from tube_scout.services.takeout_ingest import parse_takeout_csv_metadata

        takeout_root, meta_dir, channel_dir = _make_takeout_tree(tmp_path)
        _write_channel_csv(channel_dir / "채널.csv")
        with (meta_dir / "동영상.csv").open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=_REAL_VIDEO_HEADER)
            w.writeheader()
            w.writerow(_video_row("vid_ok1", privacy="비공개"))
            w.writerow(_video_row("vid_unknown", privacy="예약 공개"))
            w.writerow(_video_row("vid_ok2", privacy="공개"))

        _, videos = parse_takeout_csv_metadata(takeout_root)
        video_ids = {v.video_id for v in videos}

        # vid_unknown must be skipped (unknown privacy), vid_ok1 and vid_ok2 must survive
        assert "vid_ok1" in video_ids
        assert "vid_ok2" in video_ids
        assert "vid_unknown" not in video_ids

    def test_unknown_privacy_produces_audit_row(self, tmp_path: Path) -> None:
        """ingest_takeout() must write audit row with reason=unknown_privacy_value."""
        from tube_scout.services.takeout_ingest import ingest_takeout

        takeout_root, meta_dir, channel_dir = _make_takeout_tree(tmp_path)
        _write_channel_csv(channel_dir / "채널.csv")
        with (meta_dir / "동영상.csv").open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=_REAL_VIDEO_HEADER)
            w.writeheader()
            w.writerow(_video_row("vid_ok1", privacy="비공개"))
            w.writerow(_video_row("vid_unknown", privacy="예약 공개"))

        work_root = tmp_path / "data"

        with mock.patch(
            "tube_scout.services.takeout_ingest._load_alias_registry",
            return_value={"nursing": mock.MagicMock(channel_id="UCtest001")},
        ):
            ingest_takeout(
                takeout_dir=takeout_root,
                channel_alias="nursing",
                db_path=tmp_path / "test.db",
                work_root=work_root,
                dry_run=False,
            )

        audit_csv = work_root / "nursing" / "01_collect" / "takeout_ingest_audit.csv"
        assert audit_csv.exists(), f"Audit CSV not found at {audit_csv}"

        rows = list(csv.DictReader(audit_csv.open(encoding="utf-8")))
        skip_rows = [r for r in rows if r.get("reason") == "unknown_privacy_value"]
        assert len(skip_rows) >= 1, f"No unknown_privacy_value audit row found. rows={rows}"
        assert skip_rows[0]["raw_value"] == "예약 공개"

    def test_known_korean_privacy_values_accepted(self, tmp_path: Path) -> None:
        """'비공개', '일부 공개', '공개' must all be parsed and NOT skipped."""
        from tube_scout.services.takeout_ingest import parse_takeout_csv_metadata

        takeout_root, meta_dir, channel_dir = _make_takeout_tree(tmp_path)
        _write_channel_csv(channel_dir / "채널.csv")
        with (meta_dir / "동영상.csv").open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=_REAL_VIDEO_HEADER)
            w.writeheader()
            w.writerow(_video_row("vid_private", privacy="비공개"))
            w.writerow(_video_row("vid_unlisted", privacy="일부 공개"))
            w.writerow(_video_row("vid_public", privacy="공개"))

        _, videos = parse_takeout_csv_metadata(takeout_root)
        video_ids = {v.video_id for v in videos}
        assert {"vid_private", "vid_unlisted", "vid_public"} == video_ids

        by_id = {v.video_id: v for v in videos}
        assert by_id["vid_private"].privacy_status == "private"
        assert by_id["vid_unlisted"].privacy_status == "unlisted"
        assert by_id["vid_public"].privacy_status == "public"
