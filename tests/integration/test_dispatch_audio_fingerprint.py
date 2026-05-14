"""T036+T037 RED — dispatch_audio_fingerprint lifecycle + idempotent skip."""
import datetime
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_FPCALC_DURATION = 240
_FPCALC_FP = "AQADtFMSRUkiJdmEjzoqJIkSJUqSKEmSJEmSREmSJEmUJEmSJEmSJEmSJEmSJEmS"
_FPCALC_STDOUT = f"DURATION={_FPCALC_DURATION}\nFINGERPRINT={_FPCALC_FP}\n"


def _make_ytdlp_audio_result(mp3_path: Path) -> MagicMock:
    proc = MagicMock(spec=subprocess.CompletedProcess)
    proc.returncode = 0
    proc.stdout = f"[ExtractAudio] Destination: {mp3_path}"
    proc.stderr = ""
    return proc


def _make_fpcalc_result() -> MagicMock:
    proc = MagicMock(spec=subprocess.CompletedProcess)
    proc.returncode = 0
    proc.stdout = _FPCALC_STDOUT
    proc.stderr = ""
    return proc


def _make_video_meta(video_id: str) -> dict:
    return {
        "video_id": video_id,
        "title": f"Test Lecture {video_id}",
        "published_at": "2024-01-01T00:00:00Z",
    }


def test_dispatch_audio_fingerprint_lifecycle_try_finally(tmp_path: Path) -> None:
    """T036: dispatch_audio_fingerprint deletes audio in try/finally — audio_temp empty after call."""
    from tube_scout.cli.collect import dispatch_audio_fingerprint
    from tube_scout.storage.content_db import audio_fingerprint_exists, migrate_to_v3

    audio_temp = tmp_path / "audio_temp"
    audio_temp.mkdir()
    db_path = tmp_path / "content_reuse.db"
    migrate_to_v3(db_path)

    video_id = "DISPATCH001"
    mp3_file = audio_temp / f"{video_id}.mp3"

    def write_mp3(cmd, **kwargs):
        mp3_file.write_bytes(b"\x00" * 100)
        return _make_ytdlp_audio_result(mp3_file)

    with (
        patch("subprocess.run", side_effect=write_mp3) as mock_run,
        patch(
            "tube_scout.cli.collect.dispatch_audio_fingerprint",
            wraps=lambda **kw: None,
        ),
    ):
        pass  # dispatch_audio_fingerprint is the thing we're testing

    # Call dispatch directly with mocked subprocess
    call_count = [0]

    def subprocess_router(cmd, **kwargs):
        call_count[0] += 1
        if "fpcalc" in cmd[0]:
            return _make_fpcalc_result()
        # yt-dlp
        mp3_file.write_bytes(b"\x00" * 100)
        return _make_ytdlp_audio_result(mp3_file)

    with patch("subprocess.run", side_effect=subprocess_router):
        dispatch_audio_fingerprint(
            channel=None,
            all_channels=False,
            force=False,
            audio_temp=audio_temp,
            db_path=db_path,
            video_ids=[video_id],
            cookies_browser="brave",
            sleep_seconds=(0.0, 0.0),
        )

    remaining = list(audio_temp.glob("*.mp3"))
    assert remaining == [], f"SC-004 violated: audio files remain: {remaining}"


def test_dispatch_audio_fingerprint_idempotent_skip(tmp_path: Path) -> None:
    """T037: dispatch_audio_fingerprint skips video if fingerprint exists and force=False."""
    from tube_scout.cli.collect import dispatch_audio_fingerprint
    from tube_scout.storage.content_db import (
        audio_fingerprint_exists,
        insert_audio_fingerprint,
        migrate_to_v3,
    )

    audio_temp = tmp_path / "audio_temp"
    audio_temp.mkdir()
    db_path = tmp_path / "content_reuse.db"
    migrate_to_v3(db_path)

    video_id = "DISPATCH002"
    # Pre-insert fingerprint row
    extracted_at = datetime.datetime.now(tz=datetime.timezone.utc).isoformat()
    insert_audio_fingerprint(db_path, video_id, b"\x00" * 8, 240.0, extracted_at)
    assert audio_fingerprint_exists(db_path, video_id)

    call_log = []

    def fail_if_called(cmd, **kwargs):
        call_log.append(cmd)
        raise AssertionError(f"subprocess.run should not be called: {cmd}")

    with patch("subprocess.run", side_effect=fail_if_called):
        dispatch_audio_fingerprint(
            channel=None,
            all_channels=False,
            force=False,
            audio_temp=audio_temp,
            db_path=db_path,
            video_ids=[video_id],
            cookies_browser="brave",
            sleep_seconds=(0.0, 0.0),
        )

    assert call_log == [], "yt-dlp was called despite fingerprint existing"


def test_dispatch_audio_fingerprint_force_overrides_skip(tmp_path: Path) -> None:
    """T037b: dispatch_audio_fingerprint re-extracts if force=True even if fingerprint exists."""
    from tube_scout.cli.collect import dispatch_audio_fingerprint
    from tube_scout.storage.content_db import (
        audio_fingerprint_exists,
        insert_audio_fingerprint,
        migrate_to_v3,
    )

    audio_temp = tmp_path / "audio_temp"
    audio_temp.mkdir()
    db_path = tmp_path / "content_reuse.db"
    migrate_to_v3(db_path)

    video_id = "DISPATCH003"
    extracted_at = datetime.datetime.now(tz=datetime.timezone.utc).isoformat()
    insert_audio_fingerprint(db_path, video_id, b"\x00" * 8, 240.0, extracted_at)

    mp3_file = audio_temp / f"{video_id}.mp3"
    call_log = []

    def subprocess_router(cmd, **kwargs):
        call_log.append(cmd[0])
        if "fpcalc" in cmd[0]:
            return _make_fpcalc_result()
        mp3_file.write_bytes(b"\x00" * 100)
        return _make_ytdlp_audio_result(mp3_file)

    with patch("subprocess.run", side_effect=subprocess_router):
        dispatch_audio_fingerprint(
            channel=None,
            all_channels=False,
            force=True,
            audio_temp=audio_temp,
            db_path=db_path,
            video_ids=[video_id],
            cookies_browser="brave",
            sleep_seconds=(0.0, 0.0),
        )

    assert any("yt-dlp" in c for c in call_log), "yt-dlp should be called when force=True"
    remaining = list(audio_temp.glob("*.mp3"))
    assert remaining == [], "SC-004: audio must be deleted even with force=True"


def test_dispatch_audio_fingerprint_exception_still_cleans(tmp_path: Path) -> None:
    """T036b: dispatch_audio_fingerprint deletes audio even when fpcalc raises."""
    from tube_scout.cli.collect import dispatch_audio_fingerprint
    from tube_scout.storage.content_db import migrate_to_v3
    from tube_scout.services.audio_fingerprint import FingerprintExtractError

    audio_temp = tmp_path / "audio_temp"
    audio_temp.mkdir()
    db_path = tmp_path / "content_reuse.db"
    migrate_to_v3(db_path)

    video_id = "DISPATCH004"
    mp3_file = audio_temp / f"{video_id}.mp3"

    fail_fpcalc = MagicMock(spec=subprocess.CompletedProcess)
    fail_fpcalc.returncode = 1
    fail_fpcalc.stdout = ""
    fail_fpcalc.stderr = "ERROR: fpcalc: cannot decode"

    def subprocess_router(cmd, **kwargs):
        if "fpcalc" in cmd[0]:
            return fail_fpcalc
        mp3_file.write_bytes(b"\x00" * 100)
        return _make_ytdlp_audio_result(mp3_file)

    with patch("subprocess.run", side_effect=subprocess_router):
        dispatch_audio_fingerprint(
            channel=None,
            all_channels=False,
            force=False,
            audio_temp=audio_temp,
            db_path=db_path,
            video_ids=[video_id],
            cookies_browser="brave",
            sleep_seconds=(0.0, 0.0),
        )

    remaining = list(audio_temp.glob("*.mp3"))
    assert remaining == [], f"SC-004: audio must be deleted even on fpcalc error: {remaining}"
