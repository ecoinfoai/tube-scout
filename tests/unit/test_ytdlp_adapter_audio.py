"""T028 RED — fetch_audio_via_ytdlp 4 scenarios (subprocess mocked)."""
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


def _make_completed(returncode: int = 0, stdout: str = "", stderr: str = "") -> MagicMock:
    proc = MagicMock(spec=subprocess.CompletedProcess)
    proc.returncode = returncode
    proc.stdout = stdout
    proc.stderr = stderr
    return proc


def test_fetch_audio_postprocessor_args_uses_ffmpeg_prefix(tmp_path: Path) -> None:
    """Scenario 1: subprocess cmd must have --postprocessor-args 'ffmpeg:-ar 22050 -ac 1'."""
    from tube_scout.services.ytdlp_adapter import fetch_audio_via_ytdlp

    video_id = "AUDIO00001"
    output_dir = tmp_path / "audio_temp"
    output_dir.mkdir()
    mp3_file = output_dir / f"{video_id}.mp3"
    mp3_file.write_bytes(b"\x00" * 10)

    captured_cmd: list = []

    def spy_run(cmd, **kwargs):
        captured_cmd.extend(cmd)
        return _make_completed(0, stdout=f"[ExtractAudio] Destination: {mp3_file}")

    with patch("subprocess.run", side_effect=spy_run):
        fetch_audio_via_ytdlp(
            video_url=f"https://youtu.be/{video_id}",
            output_dir=output_dir,
            cookies_browser="brave",
            sleep_seconds=(0.0, 0.0),
        )

    cmd_str = " ".join(captured_cmd)
    assert "--postprocessor-args" in cmd_str
    assert "ffmpeg:" in cmd_str
    assert "22050" in cmd_str


def test_fetch_audio_returns_mp3_path(tmp_path: Path) -> None:
    """Scenario 2: yt-dlp writes mp3 → returns Path to mp3 file."""
    from tube_scout.services.ytdlp_adapter import fetch_audio_via_ytdlp

    video_id = "AUDIO00002"
    output_dir = tmp_path / "audio_temp"
    output_dir.mkdir()
    mp3_file = output_dir / f"{video_id}.mp3"
    mp3_file.write_bytes(b"\x00" * 10)

    mock_result = _make_completed(0, stdout=f"[ExtractAudio] Destination: {mp3_file}")

    with patch("subprocess.run", return_value=mock_result):
        result_path = fetch_audio_via_ytdlp(
            video_url=f"https://youtu.be/{video_id}",
            output_dir=output_dir,
            cookies_browser="brave",
            sleep_seconds=(0.0, 0.0),
        )

    assert result_path == mp3_file
    assert result_path.suffix == ".mp3"


def test_fetch_audio_decode_error_raises_ytdlp_audio_decode_error(tmp_path: Path) -> None:
    """Scenario 3: ffmpeg postprocessor fails → YtdlpAudioDecodeError."""
    from tube_scout.services.ytdlp_adapter import fetch_audio_via_ytdlp
    from tube_scout.services.ytdlp_errors import YtdlpAudioDecodeError

    output_dir = tmp_path / "audio_temp"
    output_dir.mkdir()

    mock_result = _make_completed(
        1,
        stderr="ERROR: ffmpeg exited with code 1\nUnsupported codec: dvd_subtitle",
    )

    with patch("subprocess.run", return_value=mock_result):
        with pytest.raises(YtdlpAudioDecodeError) as exc_info:
            fetch_audio_via_ytdlp(
                video_url="https://youtu.be/AUDIO00003",
                output_dir=output_dir,
                cookies_browser="brave",
                sleep_seconds=(0.0, 0.0),
            )

    assert "decode" in str(exc_info.value).lower() or "codec" in str(exc_info.value).lower() or "ffmpeg" in str(exc_info.value).lower()


def test_fetch_audio_cookies_file_fallback(tmp_path: Path) -> None:
    """Scenario 4: cookies_path set → --cookies flag used instead of --cookies-from-browser."""
    from tube_scout.services.ytdlp_adapter import fetch_audio_via_ytdlp

    video_id = "AUDIO00004"
    output_dir = tmp_path / "audio_temp"
    output_dir.mkdir()

    cookies_file = tmp_path / "cookies.txt"
    cookies_file.write_text("# Netscape HTTP Cookie File\n")
    cookies_file.chmod(0o600)

    mp3_file = output_dir / f"{video_id}.mp3"
    mp3_file.write_bytes(b"\x00" * 10)

    captured_cmd: list = []

    def spy_run(cmd, **kwargs):
        captured_cmd.extend(cmd)
        return _make_completed(0, stdout=f"[ExtractAudio] Destination: {mp3_file}")

    with patch("subprocess.run", side_effect=spy_run):
        fetch_audio_via_ytdlp(
            video_url=f"https://youtu.be/{video_id}",
            output_dir=output_dir,
            cookies_browser=None,
            cookies_path=cookies_file,
            sleep_seconds=(0.0, 0.0),
        )

    cmd_str = " ".join(captured_cmd)
    assert "--cookies" in cmd_str
    assert str(cookies_file) in cmd_str
    assert "--cookies-from-browser" not in cmd_str
