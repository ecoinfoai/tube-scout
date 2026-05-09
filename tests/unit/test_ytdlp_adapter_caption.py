"""T017 RED — fetch_caption_via_ytdlp 5 scenarios (subprocess mocked)."""
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


def _make_completed(returncode: int, stdout: str = "", stderr: str = "") -> MagicMock:
    proc = MagicMock(spec=subprocess.CompletedProcess)
    proc.returncode = returncode
    proc.stdout = stdout
    proc.stderr = stderr
    return proc


def test_manual_track_present(tmp_path: Path) -> None:
    """Scenario 1: yt-dlp writes manual ko.srv3 → returns (manual_path, None)."""
    from tube_scout.services.ytdlp_adapter import fetch_caption_via_ytdlp

    vid = "DUMMYVID001"
    manual_file = tmp_path / f"{vid}.ko.srv3"
    manual_file.write_text("dummy", encoding="utf-8")

    stdout = f"Writing video subtitles to: {manual_file}"
    mock_result = _make_completed(0, stdout=stdout)

    with patch("subprocess.run", return_value=mock_result):
        manual_path, auto_path = fetch_caption_via_ytdlp(
            video_url=f"https://youtu.be/{vid}",
            output_dir=tmp_path,
            cookies_browser="brave",
            sleep_seconds=(0.0, 0.0),
        )

    assert manual_path == manual_file
    assert auto_path is None


def test_only_auto_tracks(tmp_path: Path) -> None:
    """Scenario 2: yt-dlp writes only auto ko-orig.srv3 → returns (None, auto_path)."""
    from tube_scout.services.ytdlp_adapter import fetch_caption_via_ytdlp

    vid = "DUMMYVID002"
    auto_file = tmp_path / f"{vid}.ko-orig.srv3"
    auto_file.write_text("dummy", encoding="utf-8")

    stdout = f"Writing video subtitles to: {auto_file}"
    mock_result = _make_completed(0, stdout=stdout)

    with patch("subprocess.run", return_value=mock_result):
        manual_path, auto_path = fetch_caption_via_ytdlp(
            video_url=f"https://youtu.be/{vid}",
            output_dir=tmp_path,
            cookies_browser="brave",
            sleep_seconds=(0.0, 0.0),
        )

    assert manual_path is None
    assert auto_path == auto_file


def test_no_tracks_returns_none_none(tmp_path: Path) -> None:
    """Scenario 3: yt-dlp returncode=0, no srv3 files → returns (None, None)."""
    from tube_scout.services.ytdlp_adapter import fetch_caption_via_ytdlp

    mock_result = _make_completed(0, stdout="[youtube] Extracting URL: ...")

    with patch("subprocess.run", return_value=mock_result):
        manual_path, auto_path = fetch_caption_via_ytdlp(
            video_url="https://youtu.be/DUMMYVID003",
            output_dir=tmp_path,
            cookies_browser="brave",
            sleep_seconds=(0.0, 0.0),
        )

    assert manual_path is None
    assert auto_path is None


def test_auth_fail_raises_ytdlp_auth_error(tmp_path: Path) -> None:
    """Scenario 4: yt-dlp stderr cookies error → YtdlpAuthError."""
    from tube_scout.services.ytdlp_adapter import fetch_caption_via_ytdlp
    from tube_scout.services.ytdlp_errors import YtdlpAuthError

    mock_result = _make_completed(
        1,
        stderr="ERROR: Failed to extract any cookies from brave.",
    )

    with patch("subprocess.run", return_value=mock_result):
        with pytest.raises(YtdlpAuthError) as exc_info:
            fetch_caption_via_ytdlp(
                video_url="https://youtu.be/DUMMYVID004",
                output_dir=tmp_path,
                cookies_browser="brave",
                sleep_seconds=(0.0, 0.0),
            )

    assert "keyring" in str(exc_info.value).lower() or "refresh-cookies" in str(exc_info.value)


def test_rate_limit_raises_ytdlp_rate_limit_error(tmp_path: Path) -> None:
    """Scenario 5: yt-dlp stderr HTTP 429 → YtdlpRateLimitError."""
    from tube_scout.services.ytdlp_adapter import fetch_caption_via_ytdlp
    from tube_scout.services.ytdlp_errors import YtdlpRateLimitError

    mock_result = _make_completed(
        1,
        stderr="ERROR: [youtube] DUMMYVID005: HTTP Error 429: Too Many Requests",
    )

    with patch("subprocess.run", return_value=mock_result):
        with pytest.raises(YtdlpRateLimitError) as exc_info:
            fetch_caption_via_ytdlp(
                video_url="https://youtu.be/DUMMYVID005",
                output_dir=tmp_path,
                cookies_browser="brave",
                sleep_seconds=(0.0, 0.0),
            )

    assert "429" in str(exc_info.value) or "rate limit" in str(exc_info.value).lower()
