"""T029 RED — audio fingerprint full lifecycle integration (4 scenarios)."""
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_FPCALC_DURATION = 1989
_FPCALC_FP = (
    "AQADtFMSRUkiJdmEjzoqJIkSJUqSKEmSJEmSREmSJEmUJEmSJEmSJEmSJEmSJEmS"
    "JEmSJEmSJEmSJEmSJEmSJEmSJEmSJEmSJEmSJEmSJEmSJEmSJEmSJEmSJEmSJEmS"
)
_FPCALC_STDOUT = f"DURATION={_FPCALC_DURATION}\nFINGERPRINT={_FPCALC_FP}\n"
_FPCALC_SHORT_STDOUT = "DURATION=25\nFINGERPRINT=AQADtFMSRUkiJdmE\n"


def _make_fpcalc_result(returncode: int = 0, stdout: str = _FPCALC_STDOUT, stderr: str = "") -> MagicMock:
    proc = MagicMock(spec=subprocess.CompletedProcess)
    proc.returncode = returncode
    proc.stdout = stdout
    proc.stderr = stderr
    return proc


def test_full_lifecycle_extract_fingerprint_db_delete(tmp_path: Path) -> None:
    """Scenario 1: fpcalc mock → extract → DB INSERT → file unlink → DB SELECT."""
    from tube_scout.services.audio_fingerprint import extract_chromaprint_fingerprint
    from tube_scout.storage.content_db import (
        audio_fingerprint_exists,
        get_audio_fingerprint,
        insert_audio_fingerprint,
        migrate_to_v3,
    )

    video_id = "AFTEST0001"
    db_path = tmp_path / "content_reuse.db"
    audio_file = tmp_path / f"{video_id}.mp3"
    audio_file.write_bytes(b"\x00" * 100)

    # Setup DB
    migrate_to_v3(db_path)

    # Extract fingerprint (subprocess mocked)
    with patch("subprocess.run", return_value=_make_fpcalc_result()):
        fp_bytes, duration = extract_chromaprint_fingerprint(audio_file)

    # Persist to DB
    import datetime
    extracted_at = datetime.datetime.now(tz=datetime.timezone.utc).isoformat()
    insert_audio_fingerprint(db_path, video_id, fp_bytes, duration, extracted_at)

    # Delete audio (Constitution V — no persistence)
    audio_file.unlink()
    assert not audio_file.exists()

    # Verify DB row
    assert audio_fingerprint_exists(db_path, video_id)
    row = get_audio_fingerprint(db_path, video_id)
    assert row is not None
    stored_fp, stored_dur, stored_at, stored_src = row
    assert stored_fp == fp_bytes
    assert stored_dur == pytest.approx(duration, abs=1.0)


def test_too_short_audio_skip_no_db_insert(tmp_path: Path) -> None:
    """Scenario 2: 25s audio → AudioTooShortError → audit 'too_short' + DB INSERT 0."""
    from tube_scout.services.audio_fingerprint import extract_chromaprint_fingerprint
    from tube_scout.services.ytdlp_errors import AudioTooShortError
    from tube_scout.storage.content_db import audio_fingerprint_exists, migrate_to_v3
    from tube_scout.services.audit_writer import AuditWriter

    video_id = "AFTEST0002"
    db_path = tmp_path / "content_reuse.db"
    audio_file = tmp_path / f"{video_id}.mp3"
    audio_file.write_bytes(b"\x00" * 10)
    migrate_to_v3(db_path)

    with patch("subprocess.run", return_value=_make_fpcalc_result(stdout=_FPCALC_SHORT_STDOUT)):
        try:
            extract_chromaprint_fingerprint(audio_file)
            assert False, "Expected AudioTooShortError"
        except AudioTooShortError:
            pass

    # Audio still deleted even on error
    audio_file.unlink(missing_ok=True)

    # Audit row written
    writer = AuditWriter(tmp_path)
    writer.append_fingerprint_row({
        "video_id": video_id,
        "result": "skip",
        "reason": "too_short",
        "duration_sec": 25.0,
        "timestamp": "2026-01-01T00:00:00+00:00",
        "cookies_source": "",
    })

    audit_path = tmp_path / "01_collect" / "fingerprint_audit.csv"
    assert "too_short" in audit_path.read_text(encoding="utf-8")
    assert not audio_fingerprint_exists(db_path, video_id)


def test_idempotent_skip_existing_fingerprint(tmp_path: Path) -> None:
    """Scenario 3: same video_id re-processed → audit 'skip_existing', DB INSERT 0 new rows."""
    from tube_scout.storage.content_db import (
        audio_fingerprint_exists,
        insert_audio_fingerprint,
        migrate_to_v3,
    )
    from tube_scout.services.audit_writer import AuditWriter

    video_id = "AFTEST0003"
    db_path = tmp_path / "content_reuse.db"
    migrate_to_v3(db_path)

    import datetime
    extracted_at = datetime.datetime.now(tz=datetime.timezone.utc).isoformat()
    fp_bytes = b"AQADtFMSRUkiJdmE" * 2
    insert_audio_fingerprint(db_path, video_id, fp_bytes, 1989.0, extracted_at)

    # Second run: check exists → skip
    assert audio_fingerprint_exists(db_path, video_id)

    writer = AuditWriter(tmp_path)
    writer.append_fingerprint_row({
        "video_id": video_id,
        "result": "skip",
        "reason": "skip_existing",
        "duration_sec": 0.0,
        "timestamp": extracted_at,
        "cookies_source": "",
    })

    audit_path = tmp_path / "01_collect" / "fingerprint_audit.csv"
    assert "skip_existing" in audit_path.read_text(encoding="utf-8")


def test_force_overwrite_updates_db_row(tmp_path: Path) -> None:
    """Scenario 4: --force re-processes → DB row updated (extracted_at refreshed)."""
    from tube_scout.storage.content_db import (
        get_audio_fingerprint,
        insert_audio_fingerprint,
        migrate_to_v3,
    )
    from tube_scout.services.audio_fingerprint import extract_chromaprint_fingerprint

    video_id = "AFTEST0004"
    db_path = tmp_path / "content_reuse.db"
    migrate_to_v3(db_path)

    import datetime
    old_at = "2026-01-01T00:00:00+00:00"
    fp_bytes = b"AQADtFMSRUkiJdmE" * 2
    insert_audio_fingerprint(db_path, video_id, fp_bytes, 1989.0, old_at)

    # Force re-extract
    audio_file = tmp_path / f"{video_id}.mp3"
    audio_file.write_bytes(b"\x00" * 100)

    with patch("subprocess.run", return_value=_make_fpcalc_result()):
        new_fp, new_dur = extract_chromaprint_fingerprint(audio_file)

    new_at = datetime.datetime.now(tz=datetime.timezone.utc).isoformat()
    insert_audio_fingerprint(db_path, video_id, new_fp, new_dur, new_at)
    audio_file.unlink()

    row = get_audio_fingerprint(db_path, video_id)
    assert row is not None
    _, _, stored_at, _ = row
    assert stored_at == new_at
