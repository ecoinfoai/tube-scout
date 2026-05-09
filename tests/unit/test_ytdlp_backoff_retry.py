"""T056 RED — yt-dlp 429 exponential backoff retry (F-5, FR-014/FR-016/SC-009).

Verifies that fetch_caption_via_ytdlp and fetch_audio_via_ytdlp:
  - retry on HTTP 429 with exponential backoff (60→300→1800s)
  - raise YtdlpRateLimitError after 3 retries
  - succeed on retry if subsequent call returns 0
"""
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest


def _make_proc(returncode: int = 0, stdout: str = "", stderr: str = "") -> MagicMock:
    proc = MagicMock(spec=subprocess.CompletedProcess)
    proc.returncode = returncode
    proc.stdout = stdout
    proc.stderr = stderr
    return proc


def _429_proc() -> MagicMock:
    return _make_proc(returncode=1, stderr="ERROR: 429 Too Many Requests")


def test_fetch_caption_retries_on_429_then_raises(tmp_path: Path) -> None:
    """Scenario 1: 429 on all 3 attempts → YtdlpRateLimitError after backoff."""
    from tube_scout.services.ytdlp_adapter import fetch_caption_via_ytdlp
    from tube_scout.services.ytdlp_errors import YtdlpRateLimitError

    sleep_calls: list[float] = []

    with patch("subprocess.run", return_value=_429_proc()), patch(
        "time.sleep", side_effect=lambda s: sleep_calls.append(s)
    ):
        with pytest.raises(YtdlpRateLimitError):
            fetch_caption_via_ytdlp(
                video_url="https://youtu.be/TESTRATE429",
                output_dir=tmp_path,
                sleep_seconds=(0.0, 0.0),
            )

    # Must have slept at least once with backoff delays (60, 300, 1800 or subset)
    backoff_sleeps = [s for s in sleep_calls if s >= 60]
    assert len(backoff_sleeps) >= 1, f"Expected backoff sleep >=60s, got: {sleep_calls}"


def test_fetch_caption_succeeds_on_second_attempt(tmp_path: Path) -> None:
    """Scenario 2: 429 first attempt → success second attempt → returns normally."""
    from tube_scout.services.ytdlp_adapter import fetch_caption_via_ytdlp

    video_id = "TESTRETRY01"
    # Simulate yt-dlp writing srv3 on second call
    auto_srv3 = tmp_path / f"{video_id}.ko-orig.srv3"
    auto_srv3.write_text("<timedtext/>", encoding="utf-8")
    success_stdout = f"Writing video subtitles to: {auto_srv3}"

    call_count = 0

    def side_effect(cmd, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _429_proc()
        return _make_proc(stdout=success_stdout)

    sleep_calls: list[float] = []

    with patch("subprocess.run", side_effect=side_effect), patch(
        "time.sleep", side_effect=lambda s: sleep_calls.append(s)
    ):
        manual_path, auto_path = fetch_caption_via_ytdlp(
            video_url=f"https://youtu.be/{video_id}",
            output_dir=tmp_path,
            sleep_seconds=(0.0, 0.0),
        )

    assert call_count == 2, f"Expected 2 subprocess calls, got {call_count}"
    backoff_sleeps = [s for s in sleep_calls if s >= 60]
    assert len(backoff_sleeps) >= 1, "Expected at least one backoff sleep"


def test_fetch_audio_retries_on_429_then_raises(tmp_path: Path) -> None:
    """Scenario 3: fetch_audio_via_ytdlp 429 all 3 retries → YtdlpRateLimitError."""
    from tube_scout.services.ytdlp_adapter import fetch_audio_via_ytdlp
    from tube_scout.services.ytdlp_errors import YtdlpRateLimitError

    sleep_calls: list[float] = []

    with patch("subprocess.run", return_value=_429_proc()), patch(
        "time.sleep", side_effect=lambda s: sleep_calls.append(s)
    ):
        with pytest.raises(YtdlpRateLimitError):
            fetch_audio_via_ytdlp(
                video_url="https://youtu.be/AUDIORATE429",
                output_dir=tmp_path,
                sleep_seconds=(0.0, 0.0),
            )

    backoff_sleeps = [s for s in sleep_calls if s >= 60]
    assert len(backoff_sleeps) >= 1, f"Expected backoff sleep >=60s, got: {sleep_calls}"


def test_fetch_caption_backoff_schedule_is_exponential(tmp_path: Path) -> None:
    """Scenario 4: backoff schedule 60→300→1800s (FR-016 SC-009)."""
    from tube_scout.services.ytdlp_adapter import fetch_caption_via_ytdlp
    from tube_scout.services.ytdlp_errors import YtdlpRateLimitError

    sleep_calls: list[float] = []

    with patch("subprocess.run", return_value=_429_proc()), patch(
        "time.sleep", side_effect=lambda s: sleep_calls.append(s)
    ):
        with pytest.raises(YtdlpRateLimitError):
            fetch_caption_via_ytdlp(
                video_url="https://youtu.be/EXPBACKOFF",
                output_dir=tmp_path,
                sleep_seconds=(0.0, 0.0),
            )

    # Filter out pre-call random sleep (0.0 from sleep_seconds=(0,0))
    backoff_sleeps = [s for s in sleep_calls if s >= 60]
    # Expect exactly 3 backoff sleeps: 60, 300, 1800
    assert len(backoff_sleeps) == 3, f"Expected 3 backoff sleeps, got: {backoff_sleeps}"
    assert backoff_sleeps[0] == pytest.approx(60, abs=1)
    assert backoff_sleeps[1] == pytest.approx(300, abs=1)
    assert backoff_sleeps[2] == pytest.approx(1800, abs=1)
