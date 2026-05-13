"""Adversarial tests for `tube-scout collect takeout` CLI (spec 013 T032).

Target: src/tube_scout/cli/collect.py::collect_takeout_command and
        src/tube_scout/services/takeout_ingest.py::ingest_takeout

These tests poke at the new endpoint with malformed inputs, traversal paths,
empty/unicode aliases, evidence-score confusion, dry-run bypass attempts,
and concurrent ingest races. Goal is to *crash* or expose silent corruption,
not to confirm happy-path behavior.

Mocking policy:
- `_load_alias_registry` is patched per test so we never depend on
  ~/.config/tube-scout/tokens/channels.json on the developer's machine.
- ffprobe is not invoked: tests use video_meta with duration that won't
  trigger the size/duration bonus, keeping evidence scoring deterministic
  via title match alone.
"""

from __future__ import annotations

import csv
import datetime
import json
import os
import sqlite3
import threading
from pathlib import Path
from typing import Iterator

import pytest
from typer.testing import CliRunner

from tube_scout.cli.main import app
from tube_scout.models.config import ChannelRegistration
from tube_scout.services import takeout_ingest as ingest_mod


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

_YT_DIR = "YouTube 및 YouTube Music"
_META_DIR = "동영상 메타데이터"
_CHANNEL_DIR = "채널"
_VIDEO_DIR = "동영상"

VIDEO_CSV_COLS = [
    "동영상 ID", "동영상 제목", "동영상 URL", "동영상 생성 타임스탬프",
    "근사치 길이(밀리초)", "채널 ID", "카테고리", "공개상태", "오디오 언어",
]
CHANNEL_CSV_COLS = ["채널 ID", "채널 이름", "국가"]


def _write_csv(path: Path, header: list[str], rows: list[list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(rows)


def _build_takeout_skeleton(
    root: Path,
    *,
    channel_id: str = "UCadversary00000000000",
    channel_name: str = "Adv Channel",
    videos: list[dict] | None = None,
    extra_yt_items: list[str] | None = None,
) -> Path:
    """Create a minimal Takeout-shaped directory under `root`.

    Returns the takeout root (root itself).
    """
    yt = root / _YT_DIR
    chan_dir = yt / _CHANNEL_DIR
    meta_dir = yt / _META_DIR
    video_dir = yt / _VIDEO_DIR
    video_dir.mkdir(parents=True, exist_ok=True)

    _write_csv(
        chan_dir / "채널.csv",
        CHANNEL_CSV_COLS,
        [[channel_id, channel_name, "KR"]],
    )

    if videos is None:
        videos = [
            {
                "video_id": "vidAAAAAAAA1",
                "title": "Week 1 Lecture",
                "duration_ms": "60000",
                "created_at": "2026-01-01T00:00:00Z",
                "category": "Education",
                "privacy": "public",
                "language": "ko",
            }
        ]

    rows = []
    for v in videos:
        rows.append([
            v["video_id"],
            v["title"],
            f"https://youtube.com/watch?v={v['video_id']}",
            v.get("created_at", ""),
            v.get("duration_ms", "60000"),
            channel_id,
            v.get("category", "Education"),
            v.get("privacy", "public"),
            v.get("language", "ko"),
        ])
    _write_csv(meta_dir / "동영상.csv", VIDEO_CSV_COLS, rows)

    for name in (extra_yt_items or []):
        (yt / name).mkdir(parents=True, exist_ok=True)

    return root


def _make_mp4_stub(path: Path, *, size_bytes: int = 1024) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x00" * size_bytes)


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def fake_registry(monkeypatch: pytest.MonkeyPatch) -> dict[str, ChannelRegistration]:
    """Replace _load_alias_registry with an in-memory registry containing 'adv'."""
    reg = {
        "adv": ChannelRegistration(
            alias="adv",
            channel_id="UCadversary00000000000",
            channel_name="Adv Channel",
            registered_at="2026-05-13T00:00:00+00:00",
            last_used_at="2026-05-13T00:00:00+00:00",
            token_path="/tmp/adv.json",
        ),
    }
    monkeypatch.setattr(ingest_mod, "_load_alias_registry", lambda: reg)
    return reg


# ===========================================================================
# PERSONA 1 — Path lunatic: non-existent / empty / traversal --takeout-dir
# ===========================================================================
class TestPathLunatic:
    def test_takeout_dir_does_not_exist(
        self, runner: CliRunner, tmp_path: Path, fake_registry
    ) -> None:
        """Non-existent --takeout-dir must exit 3, not crash."""
        missing = tmp_path / "does_not_exist"
        result = runner.invoke(
            app,
            [
                "collect", "takeout",
                "--takeout-dir", str(missing),
                "--channel", "adv",
                "--data-dir", str(tmp_path / "data"),
            ],
        )
        assert result.exit_code == 3, f"expected exit=3, got {result.exit_code}\nstdout={result.stdout}"

    def test_empty_takeout_dir_no_youtube_subdir(
        self, runner: CliRunner, tmp_path: Path, fake_registry
    ) -> None:
        """Existing but empty --takeout-dir → no YouTube subdir → FileNotFoundError → exit 3."""
        empty = tmp_path / "empty"
        empty.mkdir()
        result = runner.invoke(
            app,
            [
                "collect", "takeout",
                "--takeout-dir", str(empty),
                "--channel", "adv",
                "--data-dir", str(tmp_path / "data"),
            ],
        )
        assert result.exit_code == 3, (
            f"empty takeout dir should be path error, got exit={result.exit_code}"
        )

    def test_takeout_dir_is_a_file_not_dir(
        self, runner: CliRunner, tmp_path: Path, fake_registry
    ) -> None:
        """--takeout-dir pointing at a regular file should not crash with stacktrace."""
        f = tmp_path / "iam_a_file.txt"
        f.write_text("not a dir")
        result = runner.invoke(
            app,
            [
                "collect", "takeout",
                "--takeout-dir", str(f),
                "--channel", "adv",
                "--data-dir", str(tmp_path / "data"),
            ],
        )
        # Must not exit 0 (success) on a non-dir path.
        assert result.exit_code != 0, "non-directory --takeout-dir must be rejected"

    def test_takeout_dir_relative_traversal(
        self, runner: CliRunner, tmp_path: Path, fake_registry
    ) -> None:
        """Relative '../../etc' style path should not silently succeed.

        The CLI does not resolve, but Path("../../etc").exists() check still
        happens against CWD. We expect either exit 3 (path error) or some
        non-zero — never exit 0.
        """
        result = runner.invoke(
            app,
            [
                "collect", "takeout",
                "--takeout-dir", "../../etc/this_should_not_exist",
                "--channel", "adv",
                "--data-dir", str(tmp_path / "data"),
            ],
        )
        assert result.exit_code != 0


# ===========================================================================
# PERSONA 2 — Alias injection / empty / unicode channel
# ===========================================================================
class TestAliasInjection:
    def test_unregistered_alias_exits_2(
        self, runner: CliRunner, tmp_path: Path, fake_registry
    ) -> None:
        """Unknown alias must exit 2 (ValueError path)."""
        root = _build_takeout_skeleton(tmp_path / "tk")
        result = runner.invoke(
            app,
            [
                "collect", "takeout",
                "--takeout-dir", str(root),
                "--channel", "totally_unregistered_alias",
                "--data-dir", str(tmp_path / "data"),
            ],
        )
        assert result.exit_code == 2

    def test_empty_string_alias(
        self, runner: CliRunner, tmp_path: Path, fake_registry
    ) -> None:
        """`--channel ''` must not be accepted as a registered alias."""
        root = _build_takeout_skeleton(tmp_path / "tk")
        result = runner.invoke(
            app,
            [
                "collect", "takeout",
                "--takeout-dir", str(root),
                "--channel", "",
                "--data-dir", str(tmp_path / "data"),
            ],
        )
        # Empty alias is not in fake_registry → exit 2
        assert result.exit_code == 2

    def test_alias_with_path_separator(
        self, runner: CliRunner, tmp_path: Path, fake_registry
    ) -> None:
        """Alias containing '/' or '..' must not enable directory traversal in data-dir."""
        root = _build_takeout_skeleton(tmp_path / "tk")
        data_root = tmp_path / "data"
        result = runner.invoke(
            app,
            [
                "collect", "takeout",
                "--takeout-dir", str(root),
                "--channel", "../escape",
                "--data-dir", str(data_root),
            ],
        )
        # Not registered → exit 2. Critically, no '../escape' directory should
        # have been created above data_root.
        assert result.exit_code == 2
        escaped = data_root.parent / "escape"
        assert not escaped.exists(), (
            f"path-traversal alias created a directory outside --data-dir: {escaped}"
        )

    def test_unicode_lookalike_alias(
        self, runner: CliRunner, tmp_path: Path, fake_registry
    ) -> None:
        """'аdv' (Cyrillic 'а') must NOT match 'adv' (Latin)."""
        root = _build_takeout_skeleton(tmp_path / "tk")
        result = runner.invoke(
            app,
            [
                "collect", "takeout",
                "--takeout-dir", str(root),
                "--channel", "аdv",  # Cyrillic а + dv
                "--data-dir", str(tmp_path / "data"),
            ],
        )
        assert result.exit_code == 2, "Cyrillic homoglyph must not collide with Latin alias"


# ===========================================================================
# PERSONA 3 — CSV demolitionist
# ===========================================================================
class TestCsvDemolition:
    def test_video_csv_missing_required_column(
        self, runner: CliRunner, tmp_path: Path, fake_registry
    ) -> None:
        """Removing '오디오 언어' column triggers ValueError → exit 4 in CLI."""
        root = tmp_path / "tk"
        yt = root / _YT_DIR
        (yt / _CHANNEL_DIR).mkdir(parents=True, exist_ok=True)
        (yt / _META_DIR).mkdir(parents=True, exist_ok=True)
        (yt / _VIDEO_DIR).mkdir(parents=True, exist_ok=True)
        _write_csv(
            yt / _CHANNEL_DIR / "채널.csv",
            CHANNEL_CSV_COLS,
            [["UCadversary00000000000", "Adv", "KR"]],
        )
        # Drop "오디오 언어"
        broken_cols = [c for c in VIDEO_CSV_COLS if c != "오디오 언어"]
        _write_csv(yt / _META_DIR / "동영상.csv", broken_cols, [
            ["v1", "T", "u", "", "1000", "UCadversary00000000000", "Edu", "public"],
        ])

        result = runner.invoke(
            app,
            [
                "collect", "takeout",
                "--takeout-dir", str(root),
                "--channel", "adv",
                "--data-dir", str(tmp_path / "data"),
            ],
        )
        # Missing column → ValueError → wrapped as exit 4 (DB/unexpected)
        assert result.exit_code != 0
        # And nothing should have been persisted to DB.
        db = tmp_path / "data" / "content_reuse.db"
        if db.exists():
            with sqlite3.connect(db) as conn:
                row = conn.execute("SELECT COUNT(*) FROM video_metadata").fetchone()
                assert row[0] == 0, "broken CSV must not write any video_metadata rows"

    def test_video_csv_empty_file(
        self, runner: CliRunner, tmp_path: Path, fake_registry
    ) -> None:
        """동영상.csv with zero rows (header only) → 0 videos, must not crash."""
        root = tmp_path / "tk"
        yt = root / _YT_DIR
        _write_csv(
            yt / _CHANNEL_DIR / "채널.csv",
            CHANNEL_CSV_COLS,
            [["UCadversary00000000000", "Adv", "KR"]],
        )
        _write_csv(yt / _META_DIR / "동영상.csv", VIDEO_CSV_COLS, [])
        (yt / _VIDEO_DIR).mkdir(parents=True, exist_ok=True)

        result = runner.invoke(
            app,
            [
                "collect", "takeout",
                "--takeout-dir", str(root),
                "--channel", "adv",
                "--data-dir", str(tmp_path / "data"),
            ],
        )
        # Empty rows are valid (no videos). Service should not crash.
        assert result.exit_code == 0, (
            f"empty 동영상.csv (header only) should succeed with 0 rows; "
            f"got exit={result.exit_code}, stdout={result.stdout}"
        )
        assert "total=0" in result.stdout

    def test_video_csv_malformed_duration(
        self, runner: CliRunner, tmp_path: Path, fake_registry
    ) -> None:
        """Non-numeric duration → currently `float()` will raise ValueError → exit 4."""
        root = tmp_path / "tk"
        yt = root / _YT_DIR
        _write_csv(
            yt / _CHANNEL_DIR / "채널.csv",
            CHANNEL_CSV_COLS,
            [["UCadversary00000000000", "Adv", "KR"]],
        )
        _write_csv(yt / _META_DIR / "동영상.csv", VIDEO_CSV_COLS, [
            ["v1", "T", "u", "", "NOT_A_NUMBER", "UCadversary00000000000",
             "Edu", "public", "ko"],
        ])
        (yt / _VIDEO_DIR).mkdir(parents=True, exist_ok=True)

        result = runner.invoke(
            app,
            [
                "collect", "takeout",
                "--takeout-dir", str(root),
                "--channel", "adv",
                "--data-dir", str(tmp_path / "data"),
            ],
        )
        # Garbage duration is currently NOT defensively handled — float()
        # raises and CLI returns exit 4. That's acceptable (fail-fast) but
        # exit 0 would be a silent-corruption bug.
        assert result.exit_code != 0, (
            "malformed duration must not silently succeed"
        )

    def test_channel_csv_missing(
        self, runner: CliRunner, tmp_path: Path, fake_registry
    ) -> None:
        """Missing 채널.csv → FileNotFoundError → exit 3."""
        root = tmp_path / "tk"
        yt = root / _YT_DIR
        (yt / _CHANNEL_DIR).mkdir(parents=True, exist_ok=True)
        # Note: no 채널.csv created
        (yt / _META_DIR).mkdir(parents=True, exist_ok=True)
        _write_csv(yt / _META_DIR / "동영상.csv", VIDEO_CSV_COLS, [])
        (yt / _VIDEO_DIR).mkdir(parents=True, exist_ok=True)

        result = runner.invoke(
            app,
            [
                "collect", "takeout",
                "--takeout-dir", str(root),
                "--channel", "adv",
                "--data-dir", str(tmp_path / "data"),
            ],
        )
        assert result.exit_code == 3


# ===========================================================================
# PERSONA 4 — Dry-run bypass attempts
# ===========================================================================
class TestDryRunBypass:
    def test_dry_run_writes_no_db(
        self, runner: CliRunner, tmp_path: Path, fake_registry
    ) -> None:
        """--dry-run must not create the SQLite DB or write any rows."""
        root = _build_takeout_skeleton(tmp_path / "tk")
        data_dir = tmp_path / "data"
        result = runner.invoke(
            app,
            [
                "collect", "takeout",
                "--takeout-dir", str(root),
                "--channel", "adv",
                "--dry-run",
                "--data-dir", str(data_dir),
            ],
        )
        assert result.exit_code == 0
        db_path = data_dir / "content_reuse.db"
        assert not db_path.exists(), (
            "--dry-run must NOT create content_reuse.db"
        )

    def test_dry_run_writes_no_videos_meta(
        self, runner: CliRunner, tmp_path: Path, fake_registry
    ) -> None:
        """--dry-run must not write channel_meta.json / videos_meta.json."""
        root = _build_takeout_skeleton(tmp_path / "tk")
        data_dir = tmp_path / "data"
        result = runner.invoke(
            app,
            [
                "collect", "takeout",
                "--takeout-dir", str(root),
                "--channel", "adv",
                "--dry-run",
                "--data-dir", str(data_dir),
            ],
        )
        assert result.exit_code == 0
        ch_dir = data_dir / "adv"
        assert not (ch_dir / "channel_meta.json").exists()
        assert not (ch_dir / "videos_meta.json").exists()

    def test_dry_run_does_not_symlink_mp4s(
        self, runner: CliRunner, tmp_path: Path, fake_registry
    ) -> None:
        """--dry-run must NOT create mp4 symlinks under data-dir."""
        root = _build_takeout_skeleton(tmp_path / "tk")
        mp4_path = root / _YT_DIR / _VIDEO_DIR / "Week 1 Lecture.mp4"
        _make_mp4_stub(mp4_path)

        data_dir = tmp_path / "data"
        result = runner.invoke(
            app,
            [
                "collect", "takeout",
                "--takeout-dir", str(root),
                "--channel", "adv",
                "--dry-run",
                "--data-dir", str(data_dir),
            ],
        )
        assert result.exit_code == 0
        ch_video_dir = data_dir / "adv" / _VIDEO_DIR
        # The work dir might not even exist; that's fine.
        if ch_video_dir.exists():
            assert list(ch_video_dir.iterdir()) == [], (
                "--dry-run must not symlink/copy mp4 into work dir"
            )


# ===========================================================================
# PERSONA 5 — Evidence-score gaslighter (adversarial mp4 filenames)
# ===========================================================================
class TestEvidenceScoreGaslighting:
    def test_many_videos_same_title_yields_ambiguous(
        self, runner: CliRunner, tmp_path: Path, fake_registry
    ) -> None:
        """Two videos with identical titles + one matching mp4 → must be 'ambiguous'.

        Currently decide_mapping returns ambiguous when top-score is tied,
        but several callers may still proceed. Verify ambiguous_mappings
        is counted, not high.
        """
        videos = [
            {"video_id": "vid0001AAAA", "title": "Identical Title",
             "duration_ms": "1000", "created_at": "2026-01-01T00:00:00Z"},
            {"video_id": "vid0002BBBB", "title": "Identical Title",
             "duration_ms": "1000", "created_at": "2026-01-01T00:00:00Z"},
        ]
        root = _build_takeout_skeleton(tmp_path / "tk", videos=videos)
        _make_mp4_stub(root / _YT_DIR / _VIDEO_DIR / "Identical Title.mp4")

        result = runner.invoke(
            app,
            [
                "collect", "takeout",
                "--takeout-dir", str(root),
                "--channel", "adv",
                "--data-dir", str(tmp_path / "data"),
            ],
        )
        assert result.exit_code == 0
        # Ambiguous should be 1, high should be 0
        assert "ambiguous=1" in result.stdout, (
            f"duplicate-title mp4 must be ambiguous; stdout={result.stdout}"
        )
        assert "high=0" in result.stdout, (
            "duplicate-title mp4 must NOT be marked high confidence"
        )

    def test_mp4_filename_with_traversal_does_not_escape(
        self, runner: CliRunner, tmp_path: Path, fake_registry
    ) -> None:
        """mp4 filename glob can't include '../' (POSIX disallows), but
        spaces/special chars should not break audit CSV escaping."""
        weird_name = 'crash"\\nfake_col,injection.mp4'
        root = _build_takeout_skeleton(tmp_path / "tk")
        # Use weird mp4 stem; must be a valid filename on the FS
        try:
            _make_mp4_stub(root / _YT_DIR / _VIDEO_DIR / weird_name)
        except OSError:
            pytest.skip("FS rejected weird filename; not a bug in tube-scout")

        result = runner.invoke(
            app,
            [
                "collect", "takeout",
                "--takeout-dir", str(root),
                "--channel", "adv",
                "--data-dir", str(tmp_path / "data"),
            ],
        )
        # Should succeed (just an unmapped mp4); audit CSV must be valid.
        assert result.exit_code == 0
        audit = tmp_path / "data" / "adv" / "01_collect" / "takeout_ingest_audit.csv"
        assert audit.exists()
        # CSV must be parseable — if we ever generated bad CSV, the reader
        # would raise or yield wrong column counts.
        with audit.open(encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))
        assert all("mp4_filename" in r for r in rows), (
            "audit CSV header missing or rows malformed"
        )

    def test_empty_video_metadata_with_mp4_files(
        self, runner: CliRunner, tmp_path: Path, fake_registry
    ) -> None:
        """0 videos in CSV but mp4 files present → every mp4 unmapped, no crash."""
        root = tmp_path / "tk"
        yt = root / _YT_DIR
        _write_csv(
            yt / _CHANNEL_DIR / "채널.csv",
            CHANNEL_CSV_COLS,
            [["UCadversary00000000000", "Adv", "KR"]],
        )
        _write_csv(yt / _META_DIR / "동영상.csv", VIDEO_CSV_COLS, [])
        for i in range(5):
            _make_mp4_stub(yt / _VIDEO_DIR / f"Lecture {i}.mp4")

        result = runner.invoke(
            app,
            [
                "collect", "takeout",
                "--takeout-dir", str(root),
                "--channel", "adv",
                "--data-dir", str(tmp_path / "data"),
            ],
        )
        assert result.exit_code == 0
        # 5 mp4 files, all unmapped
        assert "unmapped=5" in result.stdout, (
            f"all mp4s should be unmapped; stdout={result.stdout}"
        )


# ===========================================================================
# PERSONA 6 — Idempotency / re-ingest sanity
# ===========================================================================
class TestIdempotency:
    def test_ingest_twice_does_not_duplicate_videos(
        self, runner: CliRunner, tmp_path: Path, fake_registry
    ) -> None:
        """Running ingest twice in a row must NOT double-insert video_metadata."""
        root = _build_takeout_skeleton(tmp_path / "tk")
        _make_mp4_stub(root / _YT_DIR / _VIDEO_DIR / "Week 1 Lecture.mp4")
        data_dir = tmp_path / "data"

        for _ in range(2):
            result = runner.invoke(
                app,
                [
                    "collect", "takeout",
                    "--takeout-dir", str(root),
                    "--channel", "adv",
                    "--data-dir", str(data_dir),
                ],
            )
            assert result.exit_code == 0, result.stdout

        db_path = data_dir / "content_reuse.db"
        with sqlite3.connect(db_path) as conn:
            cnt = conn.execute("SELECT COUNT(*) FROM video_metadata").fetchone()[0]
        assert cnt == 1, f"video_metadata duplicated; got {cnt} rows"


# ===========================================================================
# PERSONA 7 — DB path attacker (write to bizarre locations)
# ===========================================================================
class TestDbPathAttack:
    def test_db_path_to_unwritable_parent(
        self, runner: CliRunner, tmp_path: Path, fake_registry
    ) -> None:
        """--db-path pointing into a non-existent deep dir is auto-created.

        We don't want a stacktrace — we want graceful behavior (parent mkdir).
        """
        root = _build_takeout_skeleton(tmp_path / "tk")
        deep = tmp_path / "x" / "y" / "z" / "content_reuse.db"
        result = runner.invoke(
            app,
            [
                "collect", "takeout",
                "--takeout-dir", str(root),
                "--channel", "adv",
                "--data-dir", str(tmp_path / "data"),
                "--db-path", str(deep),
            ],
        )
        assert result.exit_code == 0, result.stdout
        assert deep.exists()

    def test_db_path_is_existing_directory(
        self, runner: CliRunner, tmp_path: Path, fake_registry
    ) -> None:
        """If --db-path points at an existing *directory* (not file), sqlite must fail.

        This must not corrupt or crash silently; exit code must be non-zero (4).
        """
        root = _build_takeout_skeleton(tmp_path / "tk")
        bad_dir = tmp_path / "iam_a_dir"
        bad_dir.mkdir()
        result = runner.invoke(
            app,
            [
                "collect", "takeout",
                "--takeout-dir", str(root),
                "--channel", "adv",
                "--data-dir", str(tmp_path / "data"),
                "--db-path", str(bad_dir),
            ],
        )
        assert result.exit_code != 0, (
            "pointing --db-path at a directory must not be treated as success"
        )


# ===========================================================================
# PERSONA 8 — Ignored CSV policy detector (FR-008)
# ===========================================================================
class TestIgnoredPolicy:
    def test_ignored_categories_are_counted_and_audited(
        self, runner: CliRunner, tmp_path: Path, fake_registry
    ) -> None:
        """Items like '동영상 녹화' '댓글' '재생목록' must be skipped, counted,
        and recorded as result=skip / reason=ignored_by_policy in audit CSV."""
        root = _build_takeout_skeleton(
            tmp_path / "tk",
            extra_yt_items=["동영상 녹화", "댓글", "재생목록", "구독정보"],
        )
        result = runner.invoke(
            app,
            [
                "collect", "takeout",
                "--takeout-dir", str(root),
                "--channel", "adv",
                "--data-dir", str(tmp_path / "data"),
            ],
        )
        assert result.exit_code == 0
        assert "ignored_csv=4" in result.stdout, (
            f"4 ignored-category dirs expected; stdout={result.stdout}"
        )
        audit = tmp_path / "data" / "adv" / "01_collect" / "takeout_ingest_audit.csv"
        with audit.open(encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))
        skip_rows = [r for r in rows if r["result"] == "skip"
                     and r["reason"] == "ignored_by_policy"]
        assert len(skip_rows) == 4

    def test_dry_run_skips_audit_write(
        self, runner: CliRunner, tmp_path: Path, fake_registry
    ) -> None:
        """--dry-run on ignored categories must not write audit rows either."""
        root = _build_takeout_skeleton(
            tmp_path / "tk",
            extra_yt_items=["동영상 녹화", "댓글"],
        )
        result = runner.invoke(
            app,
            [
                "collect", "takeout",
                "--takeout-dir", str(root),
                "--channel", "adv",
                "--dry-run",
                "--data-dir", str(tmp_path / "data"),
            ],
        )
        assert result.exit_code == 0
        audit = tmp_path / "data" / "adv" / "01_collect" / "takeout_ingest_audit.csv"
        assert not audit.exists(), (
            "--dry-run must not create takeout_ingest_audit.csv"
        )


# ===========================================================================
# PERSONA 9 — Concurrency chaos
# ===========================================================================
class TestConcurrency:
    def test_two_concurrent_ingests_same_db_no_corruption(
        self, runner: CliRunner, tmp_path: Path, fake_registry
    ) -> None:
        """Two threads call ingest_takeout on the same DB concurrently.

        Goal: SQLite serializes commits; final row count must equal 1
        (idempotent insert-or-ignore), and DB must remain readable.
        """
        root = _build_takeout_skeleton(tmp_path / "tk")
        data_dir = tmp_path / "data"
        db_path = data_dir / "content_reuse.db"
        data_dir.mkdir()

        errors: list[BaseException] = []

        def runit() -> None:
            try:
                ingest_mod.ingest_takeout(
                    takeout_dir=root,
                    channel_alias="adv",
                    db_path=db_path,
                    work_root=data_dir,
                    use_symlinks=False,
                    dry_run=False,
                )
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=runit) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # At most one "database is locked" is acceptable; both succeeding is best.
        sqlite_errors = [e for e in errors if isinstance(e, sqlite3.OperationalError)]
        unexpected = [e for e in errors if not isinstance(e, sqlite3.OperationalError)]
        assert not unexpected, f"unexpected errors during concurrent ingest: {unexpected}"

        # DB must be readable and contain exactly the single video.
        with sqlite3.connect(db_path) as conn:
            cnt = conn.execute("SELECT COUNT(*) FROM video_metadata").fetchone()[0]
        assert cnt == 1, f"concurrent ingest corrupted row count: {cnt}"
        # If any sqlite lock error happened, that's expected serialization;
        # log it but don't fail.
        if sqlite_errors:
            print(f"[adversary] concurrent ingest serialized via OperationalError: "
                  f"{len(sqlite_errors)} of 2 runs")


# ===========================================================================
# PERSONA 10 — Privacy & timestamp boundary
# ===========================================================================
class TestPrivacyAndTimestamp:
    def test_invalid_privacy_status_falls_to_none(
        self, runner: CliRunner, tmp_path: Path, fake_registry
    ) -> None:
        """Unknown privacy value ('garbage') maps to None — must not crash."""
        videos = [{
            "video_id": "vid001AAAAA",
            "title": "Title A",
            "duration_ms": "1000",
            "created_at": "2026-01-01T00:00:00Z",
            "privacy": "garbage_value",
        }]
        root = _build_takeout_skeleton(tmp_path / "tk", videos=videos)
        result = runner.invoke(
            app,
            [
                "collect", "takeout",
                "--takeout-dir", str(root),
                "--channel", "adv",
                "--data-dir", str(tmp_path / "data"),
            ],
        )
        assert result.exit_code == 0
        db = tmp_path / "data" / "content_reuse.db"
        with sqlite3.connect(db) as conn:
            row = conn.execute(
                "SELECT privacy_status FROM video_metadata WHERE video_id='vid001AAAAA'"
            ).fetchone()
        assert row is not None
        assert row[0] is None, (
            f"invalid privacy must store as NULL, got {row[0]!r}"
        )

    def test_malformed_created_at_falls_to_none(
        self, runner: CliRunner, tmp_path: Path, fake_registry
    ) -> None:
        """Non-ISO timestamp → created_at=None, no crash."""
        videos = [{
            "video_id": "vid002BBBBB",
            "title": "Title B",
            "duration_ms": "1000",
            "created_at": "yesterday-ish",
        }]
        root = _build_takeout_skeleton(tmp_path / "tk", videos=videos)
        result = runner.invoke(
            app,
            [
                "collect", "takeout",
                "--takeout-dir", str(root),
                "--channel", "adv",
                "--data-dir", str(tmp_path / "data"),
            ],
        )
        assert result.exit_code == 0
        db = tmp_path / "data" / "content_reuse.db"
        with sqlite3.connect(db) as conn:
            row = conn.execute(
                "SELECT created_at FROM video_metadata WHERE video_id='vid002BBBBB'"
            ).fetchone()
        assert row is not None
        assert row[0] is None

    def test_extremely_long_title_does_not_truncate_video_id(
        self, runner: CliRunner, tmp_path: Path, fake_registry
    ) -> None:
        """A 10_000-char title must not crash CSV parsing or DB insert.

        video_id is bounded to 20 chars by the model; an oversized title
        must not bleed across columns.
        """
        long_title = "A" * 10_000
        videos = [{
            "video_id": "vidLONG00001",
            "title": long_title,
            "duration_ms": "1000",
            "created_at": "2026-01-01T00:00:00Z",
        }]
        root = _build_takeout_skeleton(tmp_path / "tk", videos=videos)
        result = runner.invoke(
            app,
            [
                "collect", "takeout",
                "--takeout-dir", str(root),
                "--channel", "adv",
                "--data-dir", str(tmp_path / "data"),
            ],
        )
        assert result.exit_code == 0
        db = tmp_path / "data" / "content_reuse.db"
        with sqlite3.connect(db) as conn:
            row = conn.execute(
                "SELECT video_id, length(title) FROM video_metadata "
                "WHERE video_id='vidLONG00001'"
            ).fetchone()
        assert row is not None
        assert row[0] == "vidLONG00001"
        assert row[1] == 10_000


# ===========================================================================
# PERSONA 11 — Required-option enforcer
# ===========================================================================
class TestRequiredOptions:
    def test_missing_takeout_dir_flag(self, runner: CliRunner, fake_registry) -> None:
        """Missing --takeout-dir must be Typer usage error (exit 2)."""
        result = runner.invoke(app, ["collect", "takeout", "--channel", "adv"])
        assert result.exit_code != 0
        # Typer usage errors are exit 2
        assert result.exit_code == 2

    def test_missing_channel_flag(self, runner: CliRunner, tmp_path: Path, fake_registry) -> None:
        """Missing --channel must be Typer usage error."""
        result = runner.invoke(
            app, ["collect", "takeout", "--takeout-dir", str(tmp_path)],
        )
        assert result.exit_code != 0
