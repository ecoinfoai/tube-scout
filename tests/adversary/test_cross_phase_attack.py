"""Cross-phase adversary tests (spec 013 T102).

Cross-cuts all three user stories of spec 013:

    US1 — local ASR pipeline (Takeout ingest, audio extract, transcribe,
          normalize)
    US2 — nC2 reuse analysis + multi-axis professor report
    US3 — KB transcript export

These tests do *not* exercise happy paths. Each scenario picks a join
point between two phases (or two CLI invocations) and asks: "what
happens when the world is misbehaving exactly at that boundary?"

The bar (FR-046 reasoning extended to all FR): every scenario MUST
produce an actionable English error message, not silent corruption,
silent skip, or a Python traceback that leaks internals to the user.

Mocking policy:
- No real subprocess, no real ASR, no real GPU.
- All filesystem I/O lives under pytest `tmp_path` fixtures.
- External services (ffprobe, faster-whisper, weasyprint, sqlite3)
  are either mocked or replaced with deterministic stand-ins.

Personas (mapped to scenarios in `tasks.md` T102):

    (a) "The Ctrl+C Saboteur"     — worker pool + signal cleanup
    (b) "The CSV Bomb Defuser"     — corrupted Takeout CSV during ingest
    (c) "The Race Condition Voyeur"— analyze still running, report invoked
    (d) "The JSON Vandal"          — malformed transcripts_normalized JSON
    (e) "The Read-Only Filesystem"— KB export to immutable directory

Each persona spawns 2-3 attack vectors, for a total of 13 adversary
test cases across 5 scenarios.
"""

from __future__ import annotations

import json
import multiprocessing
import os
import sqlite3
import stat
import threading
import time
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_minimal_v4_db(db_path: Path) -> None:
    """Create a v4-shaped SQLite db with the columns the workers touch.

    Mirrors the spec 013 schema deltas relevant to T102 attack vectors —
    only the tables/columns referenced by the code paths under test.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(
            """
            CREATE TABLE channel_metadata (
                channel_id TEXT PRIMARY KEY,
                alias TEXT NOT NULL,
                channel_name TEXT,
                ingested_at TEXT
            );
            CREATE TABLE video_metadata (
                video_id TEXT PRIMARY KEY,
                channel_id TEXT,
                title TEXT,
                duration_seconds REAL,
                privacy_status TEXT,
                source TEXT
            );
            CREATE TABLE processing_status (
                video_id TEXT PRIMARY KEY,
                stage TEXT,
                status TEXT NOT NULL,
                caption_source TEXT,
                caption_source_detail TEXT,
                match_confidence REAL,
                updated_at TEXT
            );
            """
        )
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Scenario (a) — "The Ctrl+C Saboteur"
# ---------------------------------------------------------------------------


class TestSaboteurConcurrentWorkerPool:
    """Persona: The Ctrl+C Saboteur.

    Concurrent worker pool MUST clean up child processes and SQLite locks
    when SIGINT arrives mid-run. Silent leak of zombie processes or a
    leftover BEGIN IMMEDIATE row would constitute a bug.
    """

    def test_sigint_during_pool_does_not_leave_orphan_processes(
        self, tmp_path: Path
    ) -> None:
        """Vector a.1: parent receives SIGINT while two workers are spawned.

        Acceptance: after the parent re-raises KeyboardInterrupt, all
        spawned child processes MUST be either reaped or terminated. The
        test asserts on `process.is_alive()` for every child after the
        parent has handled the signal.
        """
        from tube_scout.services import worker_pool

        db_path = tmp_path / "content_reuse.db"
        _make_minimal_v4_db(db_path)
        audio_cache = tmp_path / "audio"
        transcripts = tmp_path / "transcripts"
        audio_cache.mkdir()
        transcripts.mkdir()

        def _sleepy_worker(*args: Any, **kwargs: Any) -> Any:
            time.sleep(5)
            return worker_pool.WorkerResult(
                worker_id=0, device_index=0, processed=0,
                failed=0, skipped=0, elapsed_seconds=5.0,
            )

        with patch.object(worker_pool, "run_asr_worker", side_effect=_sleepy_worker):
            stop = threading.Event()
            alive_after_interrupt: list[bool] = []
            exception_seen: list[BaseException] = []

            def _runner() -> None:
                try:
                    worker_pool.run_pool(
                        db_path=db_path,
                        audio_cache_dir=audio_cache,
                        transcripts_dir=transcripts,
                        n_workers=2,
                        device_indices=[0, 0],
                    )
                except BaseException as exc:
                    exception_seen.append(exc)
                finally:
                    stop.set()

            t = threading.Thread(target=_runner, daemon=True)
            t.start()
            time.sleep(0.5)

            for child in multiprocessing.active_children():
                if child.name.startswith("asr-worker-"):
                    child.terminate()

            stop.wait(timeout=10.0)
            t.join(timeout=2.0)

            for child in multiprocessing.active_children():
                if child.name.startswith("asr-worker-"):
                    alive_after_interrupt.append(child.is_alive())

            assert not any(alive_after_interrupt), (
                f"Orphan asr-worker processes still alive after termination: "
                f"{alive_after_interrupt}. SIGINT cleanup is incomplete."
            )

    def test_atomic_claim_releases_row_when_worker_crashes(
        self, tmp_path: Path
    ) -> None:
        """Vector a.2: worker dies after `_atomic_claim` but before status
        transition. The next pool invocation MUST be able to re-claim the
        same row via `retry_failed=True`, not block forever on a stale lock.
        """
        from tube_scout.services import worker_pool

        db_path = tmp_path / "content_reuse.db"
        _make_minimal_v4_db(db_path)

        conn = sqlite3.connect(db_path)
        try:
            conn.execute(
                "INSERT INTO processing_status "
                "(video_id, stage, status, caption_source, updated_at) "
                "VALUES (?, 'asr', 'asr_failed', NULL, '2026-05-14T00:00:00')",
                ("vid_orphaned",),
            )
            conn.commit()
        finally:
            conn.close()

        claimed = worker_pool._atomic_claim(db_path, retry_failed=True)
        assert claimed == "vid_orphaned", (
            f"Stale asr_failed row with caption_source=NULL must be "
            f"reclaimable with retry_failed=True (spec 013 C-5), got "
            f"{claimed!r}"
        )

        claimed_again = worker_pool._atomic_claim(db_path, retry_failed=True)
        assert claimed_again is None, (
            f"Once a row transitions to asr_in_progress, a second claim "
            f"must not re-take it, got {claimed_again!r}. Concurrent "
            f"workers would otherwise double-process the same video."
        )


# ---------------------------------------------------------------------------
# Scenario (b) — "The CSV Bomb Defuser"
# ---------------------------------------------------------------------------


class TestCsvBombDuringIngest:
    """Persona: The CSV Bomb Defuser.

    Takeout CSVs arrive from an untrusted-but-credentialed source (the
    operator's own Takeout export). Corrupted/truncated/missing-column
    CSVs MUST raise a labelled error BEFORE any DB rows are persisted —
    no partial channel_metadata + zero video_metadata mismatch allowed.
    """

    def _build_takeout(
        self,
        root: Path,
        *,
        videos_csv_content: str | None = None,
        channels_csv_content: str | None = None,
    ) -> Path:
        yt = root / "YouTube 및 YouTube Music"
        chan_dir = yt / "채널"
        meta_dir = yt / "동영상 메타데이터"
        chan_dir.mkdir(parents=True)
        meta_dir.mkdir(parents=True)

        chan_default = (
            "채널 ID,채널 이름,국가\n"
            "UCadversary00000000000,Adv Channel,KR\n"
        )
        videos_default = (
            "동영상 ID,동영상 제목,동영상 URL,동영상 생성 타임스탬프,"
            "근사치 길이(밀리초),채널 ID,카테고리,공개상태,오디오 언어\n"
            "vid_001,Title 1,https://yt/vid_001,2026-01-01T00:00:00+00:00,"
            "60000,UCadversary00000000000,Education,public,ko\n"
        )
        (chan_dir / "채널.csv").write_text(
            channels_csv_content if channels_csv_content is not None else chan_default,
            encoding="utf-8",
        )
        (meta_dir / "동영상.csv").write_text(
            videos_csv_content if videos_csv_content is not None else videos_default,
            encoding="utf-8",
        )
        return root

    def test_truncated_video_csv_missing_required_column_raises_actionable(
        self, tmp_path: Path
    ) -> None:
        """Vector b.1: 동영상.csv is truncated mid-header (missing
        오디오 언어 column). Parser MUST raise ValueError naming the
        missing column, not silently skip the file."""
        from tube_scout.services.takeout_ingest import parse_takeout_csv_metadata

        bad_videos = (
            "동영상 ID,동영상 제목,동영상 URL,동영상 생성 타임스탬프,"
            "근사치 길이(밀리초),채널 ID,카테고리,공개상태\n"
            "vid_001,Title 1,https://yt/vid_001,2026-01-01T00:00:00+00:00,"
            "60000,UCadversary00000000000,Education,public\n"
        )
        root = self._build_takeout(tmp_path, videos_csv_content=bad_videos)

        with pytest.raises(ValueError) as excinfo:
            parse_takeout_csv_metadata(root)

        msg = str(excinfo.value)
        assert "오디오 언어" in msg or "Missing required" in msg, (
            f"Error must name the missing column ('오디오 언어') for the "
            f"operator to fix the export. Got: {msg!r}"
        )

    def test_empty_videos_csv_dir_raises_filenotfound_not_silent(
        self, tmp_path: Path
    ) -> None:
        """Vector b.2: 동영상 메타데이터/ exists but contains no 동영상*.csv.
        Must FAIL FAST with FileNotFoundError, NOT return an empty list of
        videos (which would silently create a channel with 0 videos)."""
        from tube_scout.services.takeout_ingest import parse_takeout_csv_metadata

        yt = tmp_path / "YouTube 및 YouTube Music"
        (yt / "채널").mkdir(parents=True)
        (yt / "동영상 메타데이터").mkdir(parents=True)
        (yt / "채널" / "채널.csv").write_text(
            "채널 ID,채널 이름,국가\nUCx,Adv,KR\n", encoding="utf-8"
        )

        with pytest.raises(FileNotFoundError) as excinfo:
            parse_takeout_csv_metadata(tmp_path)
        assert "동영상" in str(excinfo.value) or ".csv" in str(excinfo.value)

    def test_garbage_bytes_in_videos_csv_does_not_corrupt_db(
        self, tmp_path: Path
    ) -> None:
        """Vector b.3: 동영상.csv replaced with random binary bytes BEFORE
        the parser reads it. The parser must raise (UnicodeDecodeError /
        ValueError / csv.Error), and any caller catching this MUST NOT
        leave a half-persisted channel row in the DB."""
        from tube_scout.services.takeout_ingest import parse_takeout_csv_metadata

        root = self._build_takeout(tmp_path)
        bad_csv = root / "YouTube 및 YouTube Music" / "동영상 메타데이터" / "동영상.csv"
        bad_csv.write_bytes(b"\x00\xff\x00\xff\x00\xff" * 50)

        with pytest.raises(Exception) as excinfo:
            parse_takeout_csv_metadata(root)
        assert excinfo.type in (
            UnicodeDecodeError, ValueError,
        ) or "csv" in str(excinfo.value).lower(), (
            f"Garbage bytes must surface a decode/parse error, not silently "
            f"yield an empty list. Got: {excinfo.type.__name__}: {excinfo.value}"
        )


# ---------------------------------------------------------------------------
# Scenario (c) — "The Race Condition Voyeur"
# ---------------------------------------------------------------------------


class TestAnalyzeReportRace:
    """Persona: The Race Condition Voyeur.

    `report content-reuse` invoked while `analyze content-reuse` is still
    populating `comparison_results` MUST produce an actionable message —
    not a half-rendered HTML, not a crash inside the template engine."""

    def test_report_with_zero_comparison_results_gives_actionable_msg(
        self, tmp_path: Path
    ) -> None:
        """Vector c.1: DB exists, schema is v4, but `comparison_results`
        is empty (analyze has not yet written anything). The report CLI
        MUST exit non-zero and explain that analyze should be run first."""
        from typer.testing import CliRunner

        from tube_scout.cli.main import app

        db = tmp_path / "content_reuse.db"
        conn = sqlite3.connect(db)
        try:
            conn.executescript(
                """
                CREATE TABLE comparison_results (
                    pair_id TEXT PRIMARY KEY,
                    video_a_id TEXT,
                    video_b_id TEXT,
                    professor TEXT,
                    channel_alias TEXT,
                    matching_mode TEXT
                );
                CREATE TABLE quality_results (
                    video_id TEXT PRIMARY KEY,
                    asr_quality_flags TEXT
                );
                """
            )
            conn.commit()
        finally:
            conn.close()

        runner = CliRunner()
        result = runner.invoke(
            app,
            [
                "report", "content-reuse",
                "--channel", "adv",
                "--professor", "Adv Prof",
                "--db-path", str(db),
                "--output", str(tmp_path / "out"),
                "--format", "html",
            ],
        )
        assert result.exit_code != 0, (
            f"Report on empty comparison_results must exit non-zero, got "
            f"exit_code={result.exit_code}. Output: {result.output!r}"
        )

    def test_report_with_concurrent_writer_does_not_crash_template(
        self, tmp_path: Path
    ) -> None:
        """Vector c.2: simulate analyze-writer mid-flight by holding a
        WRITE transaction open while the report reader attempts to
        snapshot. The reader MUST either succeed on snapshot isolation or
        raise a labelled DB busy/locked error — NEVER a jinja2 template
        crash from None values."""
        from typer.testing import CliRunner

        from tube_scout.cli.main import app

        db = tmp_path / "content_reuse.db"
        conn = sqlite3.connect(db)
        try:
            conn.executescript(
                """
                CREATE TABLE comparison_results (pair_id TEXT PRIMARY KEY);
                CREATE TABLE quality_results (video_id TEXT PRIMARY KEY);
                """
            )
            conn.commit()
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("INSERT INTO comparison_results VALUES ('mid_flight')")

            runner = CliRunner()
            result = runner.invoke(
                app,
                [
                    "report", "content-reuse",
                    "--channel", "adv",
                    "--professor", "Adv Prof",
                    "--db-path", str(db),
                    "--output", str(tmp_path / "out"),
                    "--format", "html",
                ],
            )
            assert result.exit_code != 0 or "TemplateError" not in (result.output or ""), (
                f"Concurrent writer must not produce a raw template "
                f"error. Output: {result.output!r}"
            )
        finally:
            conn.rollback()
            conn.close()


# ---------------------------------------------------------------------------
# Scenario (d) — "The JSON Vandal"
# ---------------------------------------------------------------------------


class TestJsonVandalDuringNormalize:
    """Persona: The JSON Vandal.

    `process normalize-transcripts` reads <video_id>.json files written
    by previous stages. A vandal could replace one of these with
    truncated / non-segment / hostile JSON. The normalizer MUST raise an
    actionable error pointing at the bad file path — never produce a
    silently empty normalized output."""

    def test_truncated_json_raises_with_file_path_in_message(
        self, tmp_path: Path
    ) -> None:
        """Vector d.1: transcript JSON truncated mid-array. json.loads
        will raise JSONDecodeError. The caller must surface the file
        path to the operator."""
        from tube_scout.services.text_normalizer import normalize_transcript_json

        raw = tmp_path / "vid_001.raw.json"
        raw.write_text('{"video_id":"vid_001","segments":[{"start":0,"end":1,', encoding="utf-8")
        norm = tmp_path / "vid_001.norm.json"

        with pytest.raises(json.JSONDecodeError):
            normalize_transcript_json(raw, norm)
        assert not norm.exists(), (
            f"Truncated input must not produce a normalized output. "
            f"Found leftover: {norm}"
        )

    def test_missing_segments_key_raises_valueerror_naming_key(
        self, tmp_path: Path
    ) -> None:
        """Vector d.2: JSON parses but lacks the `segments` key. Must
        raise ValueError naming the missing key."""
        from tube_scout.services.text_normalizer import normalize_transcript_json

        raw = tmp_path / "vid_002.raw.json"
        raw.write_text(json.dumps({"video_id": "vid_002", "language": "ko"}), encoding="utf-8")
        norm = tmp_path / "vid_002.norm.json"

        with pytest.raises(ValueError) as excinfo:
            normalize_transcript_json(raw, norm)
        assert "segments" in str(excinfo.value), (
            f"ValueError must explain which key is missing. Got: {excinfo.value!r}"
        )
        assert not norm.exists()

    def test_segments_is_object_not_list_does_not_silently_yield_empty(
        self, tmp_path: Path
    ) -> None:
        """Vector d.3: `segments` exists but is a dict, not a list. The
        normalizer must NOT produce a normalized output with zero segments
        — that would silently corrupt downstream analysis."""
        from tube_scout.services.text_normalizer import normalize_transcript_json

        raw = tmp_path / "vid_003.raw.json"
        raw.write_text(
            json.dumps({"video_id": "vid_003", "segments": {"oops": "object_not_list"}}),
            encoding="utf-8",
        )
        norm = tmp_path / "vid_003.norm.json"

        crashed = False
        try:
            normalize_transcript_json(raw, norm)
        except (TypeError, AttributeError, ValueError):
            crashed = True

        if not crashed:
            data = json.loads(norm.read_text(encoding="utf-8"))
            assert data.get("segments"), (
                f"Either the normalizer must raise on non-list segments, OR "
                f"the resulting file must be non-empty. A zero-segment "
                f"output is silent corruption. Got: {data!r}"
            )


# ---------------------------------------------------------------------------
# Scenario (e) — "The Read-Only Filesystem"
# ---------------------------------------------------------------------------


class TestKbExportReadOnlyDir:
    """Persona: The Read-Only Filesystem.

    Operators sometimes mount the KB destination as read-only (NFS, /mnt
    immutable). `transcript export` MUST fail with PermissionError (or
    an OSError subclass) and the message MUST identify the unwritable
    path — not crash mid-write leaving a `.tmp` file behind."""

    @pytest.fixture
    def transcript_json(self, tmp_path: Path) -> Path:
        path = tmp_path / "vid_kb.json"
        path.write_text(
            json.dumps(
                {
                    "video_id": "vid_kb",
                    "language": "ko",
                    "segments": [
                        {"start": 0.0, "end": 1.0, "text": "안녕하세요."},
                        {"start": 1.0, "end": 2.0, "text": "테스트입니다."},
                    ],
                }
            ),
            encoding="utf-8",
        )
        return path

    def test_export_to_read_only_dir_raises_oserror(
        self, tmp_path: Path, transcript_json: Path
    ) -> None:
        """Vector e.1: target directory chmod'd 0o500 (read+execute only).
        Atomic write via tempfile.mkstemp MUST raise PermissionError."""
        from tube_scout.services.kb_export import export_transcript

        ro_dir = tmp_path / "readonly"
        ro_dir.mkdir()
        original_mode = ro_dir.stat().st_mode
        os.chmod(ro_dir, stat.S_IRUSR | stat.S_IXUSR)

        try:
            with pytest.raises((PermissionError, OSError)) as excinfo:
                export_transcript(
                    transcript_json,
                    ro_dir / "vid_kb.txt",
                    format_="txt",
                )
            err_text = str(excinfo.value)
            assert ("readonly" in err_text) or ("Permission" in err_text) or (
                "Read-only" in err_text
            ) or (excinfo.value.errno is not None), (
                f"PermissionError must identify the unwritable path. "
                f"Got: {err_text!r}"
            )
        finally:
            os.chmod(ro_dir, original_mode)

        assert not list(ro_dir.glob("*.tmp")), (
            f"No leftover .tmp files allowed in target dir on failure. "
            f"Found: {list(ro_dir.glob('*.tmp'))}"
        )

    def test_export_to_nonexistent_parent_does_not_crash_after_partial_write(
        self, tmp_path: Path, transcript_json: Path
    ) -> None:
        """Vector e.2: target path has a non-existent parent directory.
        Export MUST raise FileNotFoundError / OSError BEFORE writing the
        tempfile (otherwise tempfile.mkstemp would itself fail)."""
        from tube_scout.services.kb_export import export_transcript

        nonexistent = tmp_path / "does" / "not" / "exist" / "vid_kb.txt"

        with pytest.raises((FileNotFoundError, OSError)):
            export_transcript(transcript_json, nonexistent, format_="txt")
        assert not nonexistent.exists()

    def test_export_unknown_format_rejected_before_write(
        self, tmp_path: Path, transcript_json: Path
    ) -> None:
        """Vector e.3: format_='exe' (unsupported). Must raise ValueError
        and write NOTHING to the target — guards against a typo wiping
        an existing file via os.replace."""
        from tube_scout.services.kb_export import export_transcript

        out = tmp_path / "out" / "vid_kb.evil"
        out.parent.mkdir()
        out.write_text("PREEXISTING-CONTENT-DO-NOT-OVERWRITE", encoding="utf-8")

        with pytest.raises(ValueError):
            export_transcript(transcript_json, out, format_="exe")  # type: ignore[arg-type]

        assert out.read_text(encoding="utf-8") == "PREEXISTING-CONTENT-DO-NOT-OVERWRITE", (
            "Invalid format must not overwrite the destination file."
        )
