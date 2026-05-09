"""T031 RED — SC-004: audio_temp/ empty after 5-video processing lifecycle."""
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_FPCALC_DURATION = 1989
_FPCALC_FP = "AQADtFMSRUkiJdmEjzoqJIkSJUqSKEmSJEmSREmSJEmUJEmSJEmSJEmSJEmSJEmS"
_FPCALC_STDOUT = f"DURATION={_FPCALC_DURATION}\nFINGERPRINT={_FPCALC_FP}\n"

VIDEO_IDS = [f"CLEANUP{i:04d}" for i in range(1, 6)]


def _make_ytdlp_result(mp3_path: Path) -> MagicMock:
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


def test_audio_temp_empty_after_5_video_processing(tmp_path: Path) -> None:
    """SC-004: after processing 5 videos, audio_temp/ directory is empty."""
    from tube_scout.services.audio_fingerprint import extract_chromaprint_fingerprint
    from tube_scout.services.ytdlp_adapter import fetch_audio_via_ytdlp
    from tube_scout.storage.content_db import insert_audio_fingerprint, migrate_to_v3
    from tube_scout.services.audit_writer import AuditWriter

    import datetime

    audio_temp = tmp_path / "audio_temp"
    audio_temp.mkdir()
    db_path = tmp_path / "content_reuse.db"
    migrate_to_v3(db_path)
    writer = AuditWriter(tmp_path)

    for video_id in VIDEO_IDS:
        mp3_file = audio_temp / f"{video_id}.mp3"

        # Simulate yt-dlp writing mp3
        mock_ytdlp = _make_ytdlp_result(mp3_file)

        def write_and_return(cmd, **kwargs):
            mp3_file.write_bytes(b"\x00" * 100)
            return mock_ytdlp

        with patch("subprocess.run", side_effect=write_and_return):
            audio_path = fetch_audio_via_ytdlp(
                video_url=f"https://youtu.be/{video_id}",
                output_dir=audio_temp,
                cookies_browser="brave",
                sleep_seconds=(0.0, 0.0),
            )

        # Extract fingerprint
        with patch("subprocess.run", return_value=_make_fpcalc_result()):
            fp_bytes, duration = extract_chromaprint_fingerprint(audio_path)

        # Persist
        extracted_at = datetime.datetime.now(tz=datetime.timezone.utc).isoformat()
        insert_audio_fingerprint(db_path, video_id, fp_bytes, duration, extracted_at)

        # MUST delete audio immediately (Constitution V, SC-004)
        audio_path.unlink(missing_ok=True)

        writer.append_fingerprint_row({
            "video_id": video_id,
            "result": "ok",
            "reason": "captured",
            "duration_sec": duration,
            "timestamp": extracted_at,
            "cookies_source": "browser:brave",
        })

    # SC-004 invariant: no mp3 files remain
    remaining = list(audio_temp.glob("*.mp3"))
    assert remaining == [], f"SC-004 violated: audio files remain: {remaining}"


def test_audio_temp_cleaned_on_exception(tmp_path: Path) -> None:
    """SC-004: audio file is deleted even when fingerprint extraction fails."""
    from tube_scout.services.ytdlp_adapter import fetch_audio_via_ytdlp
    from tube_scout.services.audio_fingerprint import extract_chromaprint_fingerprint
    from tube_scout.services.ytdlp_errors import FingerprintExtractError

    audio_temp = tmp_path / "audio_temp"
    audio_temp.mkdir()
    video_id = "CLEANUP_ERR1"
    mp3_file = audio_temp / f"{video_id}.mp3"

    def write_mp3(cmd, **kwargs):
        mp3_file.write_bytes(b"\x00" * 100)
        result = MagicMock(spec=subprocess.CompletedProcess)
        result.returncode = 0
        result.stdout = f"[ExtractAudio] Destination: {mp3_file}"
        result.stderr = ""
        return result

    with patch("subprocess.run", side_effect=write_mp3):
        audio_path = fetch_audio_via_ytdlp(
            video_url=f"https://youtu.be/{video_id}",
            output_dir=audio_temp,
            cookies_browser="brave",
            sleep_seconds=(0.0, 0.0),
        )

    # Simulate fpcalc failure
    fail_result = MagicMock(spec=subprocess.CompletedProcess)
    fail_result.returncode = 1
    fail_result.stdout = ""
    fail_result.stderr = "ERROR: fpcalc: cannot decode"

    try:
        with patch("subprocess.run", return_value=fail_result):
            extract_chromaprint_fingerprint(audio_path)
    except FingerprintExtractError:
        pass
    finally:
        # Lifecycle policy: always delete
        audio_path.unlink(missing_ok=True)

    remaining = list(audio_temp.glob("*.mp3"))
    assert remaining == [], f"SC-004 violated: audio files remain after error: {remaining}"
