"""T057 — P2 fixes: AT-2.4 / AT-4.5 / AT-5.3 / AT-11.1 / AT-11.3 / AT-12.3."""
import subprocess
import sys
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


def _make_proc(returncode: int = 0, stdout: str = "", stderr: str = "") -> MagicMock:
    proc = MagicMock(spec=subprocess.CompletedProcess)
    proc.returncode = returncode
    proc.stdout = stdout
    proc.stderr = stderr
    return proc


# ---------------------------------------------------------------------------
# AT-2.4: cookies env var priority chain
# ---------------------------------------------------------------------------

class TestCookiesEnvPriority:
    """AT-2.4: TUBE_SCOUT_COOKIES_FILE > TUBE_SCOUT_COOKIES_BROWSER > default."""

    def test_env_cookies_file_takes_priority_over_browser_env(self, tmp_path: Path) -> None:
        """TUBE_SCOUT_COOKIES_FILE wins over TUBE_SCOUT_COOKIES_BROWSER."""
        from tube_scout.services.ytdlp_adapter import resolve_cookies_source

        cookies_file = tmp_path / "cookies.txt"
        cookies_file.write_text("# cookies", encoding="utf-8")
        cookies_file.chmod(0o600)

        env = {
            "TUBE_SCOUT_COOKIES_FILE": str(cookies_file),
            "TUBE_SCOUT_COOKIES_BROWSER": "firefox",
        }
        result = resolve_cookies_source(env=env)
        assert result.kind == "file"
        assert result.path == cookies_file

    def test_env_browser_used_when_no_file_env(self) -> None:
        """TUBE_SCOUT_COOKIES_BROWSER used when no TUBE_SCOUT_COOKIES_FILE."""
        from tube_scout.services.ytdlp_adapter import resolve_cookies_source

        env = {"TUBE_SCOUT_COOKIES_BROWSER": "firefox"}
        result = resolve_cookies_source(env=env)
        assert result.kind == "browser"
        assert result.browser == "firefox"

    def test_default_brave_when_no_env(self, tmp_path: Path) -> None:
        """No env vars → default browser=brave (no default cookies.txt at tmp_path)."""
        from tube_scout.services.ytdlp_adapter import resolve_cookies_source

        # Patch _DEFAULT_COOKIES_PATH to a non-existent path so step 5 doesn't trigger
        with patch(
            "tube_scout.services.ytdlp_adapter._DEFAULT_COOKIES_PATH",
            tmp_path / "nonexistent_cookies.txt",
        ):
            result = resolve_cookies_source(env={})
        assert result.kind == "browser"
        assert result.browser == "brave"

    def test_cli_browser_takes_priority_over_env(self) -> None:
        """CLI cookies_browser flag wins over all env vars."""
        from tube_scout.services.ytdlp_adapter import resolve_cookies_source

        env = {
            "TUBE_SCOUT_COOKIES_BROWSER": "firefox",
            "TUBE_SCOUT_COOKIES_FILE": "/should/not/be/used",
        }
        result = resolve_cookies_source(cookies_browser="chrome", env=env)
        assert result.kind == "browser"
        assert result.browser == "chrome"


# ---------------------------------------------------------------------------
# AT-4.5: sleep 0 on first call when sleep_seconds=(0, 0)
# ---------------------------------------------------------------------------

class TestSleepZeroFirstCall:
    """AT-4.5: sleep_seconds=(0.0, 0.0) must not sleep before first yt-dlp call."""

    def test_no_sleep_when_sleep_hi_zero(self, tmp_path: Path) -> None:
        """sleep_hi=0 → time.sleep not called before subprocess."""
        from tube_scout.services.ytdlp_adapter import fetch_caption_via_ytdlp

        sleep_calls: list[float] = []

        with patch("subprocess.run", return_value=_make_proc()), patch(
            "time.sleep", side_effect=lambda s: sleep_calls.append(s)
        ):
            fetch_caption_via_ytdlp(
                video_url="https://youtu.be/TEST0000001",
                output_dir=tmp_path,
                sleep_seconds=(0.0, 0.0),
            )

        # Only backoff sleeps (>= 60s) would come from retries; no pre-call sleep expected
        pre_call_sleeps = [s for s in sleep_calls if s < 60]
        assert len(pre_call_sleeps) == 0, f"Unexpected pre-call sleeps: {sleep_calls}"


# ---------------------------------------------------------------------------
# AT-5.3: empty channel alias → KeyError / exit 5
# ---------------------------------------------------------------------------

class TestEmptyChannelAlias:
    """AT-5.3: --channel '' must raise KeyError from _dispatch_ytdlp_transcripts."""

    def test_empty_channel_raises_key_error(self, tmp_path: Path) -> None:
        """Empty string channel alias → KeyError before any yt-dlp calls."""
        from tube_scout.cli.collect import _dispatch_ytdlp_transcripts

        subprocess_calls: list = []

        def spy_run(*args, **kwargs):
            subprocess_calls.append(args)
            return _make_proc()

        mgr = MagicMock()
        mgr.project_dir = str(tmp_path)

        with patch("tube_scout.cli.collect.resolve_project", return_value=mgr), patch(
            "subprocess.run", side_effect=spy_run
        ):
            with pytest.raises(KeyError, match="empty"):
                _dispatch_ytdlp_transcripts(channel="")

        assert len(subprocess_calls) == 0, "yt-dlp must not be called for empty alias"

    def test_whitespace_only_channel_raises_key_error(self, tmp_path: Path) -> None:
        """Whitespace-only channel alias → KeyError."""
        from tube_scout.cli.collect import _dispatch_ytdlp_transcripts

        mgr = MagicMock()
        mgr.project_dir = str(tmp_path)

        with patch("tube_scout.cli.collect.resolve_project", return_value=mgr):
            with pytest.raises(KeyError, match="empty"):
                _dispatch_ytdlp_transcripts(channel="   ")


# ---------------------------------------------------------------------------
# AT-11.1: srv3 fallback scan video_id filtering
# ---------------------------------------------------------------------------

class TestSrv3FallbackVideoIdFilter:
    """AT-11.1: fallback scan must only return srv3 belonging to the requested video."""

    def test_fallback_scan_filters_by_video_id_prefix(self, tmp_path: Path) -> None:
        """Concurrent call's srv3 in same dir must not be picked up."""
        from tube_scout.services.ytdlp_adapter import fetch_caption_via_ytdlp

        target_id = "TARGET00001"
        other_id = "OTHERV00001"

        # Plant srv3 from a different video (simulates concurrent call)
        (tmp_path / f"{other_id}.ko-orig.srv3").write_text("<timedtext/>", encoding="utf-8")
        # Plant srv3 for the target video
        target_srv3 = tmp_path / f"{target_id}.ko-orig.srv3"
        target_srv3.write_text("<timedtext/>", encoding="utf-8")

        # yt-dlp stdout empty → fallback scan triggered
        with patch("subprocess.run", return_value=_make_proc(stdout="")):
            manual_path, auto_path = fetch_caption_via_ytdlp(
                video_url=f"https://youtu.be/{target_id}",
                output_dir=tmp_path,
                sleep_seconds=(0.0, 0.0),
            )

        # Must return target video's srv3, not the other one
        assert auto_path == target_srv3
        assert manual_path is None


# ---------------------------------------------------------------------------
# AT-11.3: video_id regex validation — path injection protection
# ---------------------------------------------------------------------------

class TestVideoIdValidation:
    """AT-11.3: validate_video_id must reject path-injection patterns."""

    def test_valid_video_id_passes(self) -> None:
        """11-char alphanumeric/dash/underscore → no exception."""
        from tube_scout.services.ytdlp_adapter import validate_video_id

        validate_video_id("dQw4w9WgXcQ")  # classic
        validate_video_id("AAAAAAAAAAA")
        validate_video_id("abc-def_ghi")

    def test_path_traversal_rejected(self) -> None:
        """video_id with '../' → ValueError."""
        from tube_scout.services.ytdlp_adapter import validate_video_id

        with pytest.raises(ValueError, match="Invalid video_id"):
            validate_video_id("../etc/passwd")

    def test_slash_rejected(self) -> None:
        """Slash in video_id → ValueError."""
        from tube_scout.services.ytdlp_adapter import validate_video_id

        with pytest.raises(ValueError):
            validate_video_id("abc/def/ghi")

    def test_too_short_rejected(self) -> None:
        """< 11 chars → ValueError."""
        from tube_scout.services.ytdlp_adapter import validate_video_id

        with pytest.raises(ValueError):
            validate_video_id("abc")

    def test_too_long_rejected(self) -> None:
        """> 11 chars → ValueError."""
        from tube_scout.services.ytdlp_adapter import validate_video_id

        with pytest.raises(ValueError):
            validate_video_id("AAAAAAAAAAAA")  # 12 chars

    def test_empty_rejected(self) -> None:
        """Empty string → ValueError."""
        from tube_scout.services.ytdlp_adapter import validate_video_id

        with pytest.raises(ValueError):
            validate_video_id("")

    def test_dispatch_skips_invalid_video_id(self, tmp_path: Path) -> None:
        """_dispatch_ytdlp_transcripts skips videos with invalid IDs."""
        from tube_scout.cli.collect import _dispatch_ytdlp_transcripts
        from tube_scout.services.audit_writer import AuditWriter

        channel_id = "UC_P2_AT113A"
        channel_dir = tmp_path / "01_collect" / "channels" / channel_id
        channel_dir.mkdir(parents=True)
        import json
        (channel_dir / "videos_meta.json").write_text(
            json.dumps([{"video_id": "../etc/passwd"}, {"video_id": "validID00001"}]),
            encoding="utf-8",
        )

        subprocess_calls: list = []

        def spy_run(*args, **kwargs):
            subprocess_calls.append(args)
            return _make_proc(stdout="")

        mgr = MagicMock()
        mgr.project_dir = str(tmp_path)
        audit = AuditWriter(tmp_path)

        with patch("tube_scout.cli.collect.resolve_project", return_value=mgr), patch(
            "tube_scout.cli.collect.resolve_alias_to_channel_id", return_value=channel_id
        ), patch("subprocess.run", side_effect=spy_run):
            _dispatch_ytdlp_transcripts(
                channel="nursing",
                audit_writer=audit,
                sleep_seconds=(0.0, 0.0),
            )

        # Only validID00001 should have triggered a subprocess call
        # (or no call if no captions — but invalid one must never reach subprocess)
        for call_args in subprocess_calls:
            cmd = call_args[0] if call_args else []
            assert "../etc/passwd" not in str(cmd), "path-injection video_id reached yt-dlp"


# ---------------------------------------------------------------------------
# AT-12.3: signal handler audit Exception must not be silently swallowed
# ---------------------------------------------------------------------------

class TestSignalHandlerAuditLogging:
    """AT-12.3: signal handler logs audit write failures to stderr (SS-5)."""

    def test_signal_handler_logs_audit_exception_to_stderr(self, tmp_path: Path, capsys) -> None:
        """When audit_writer.append_fingerprint_row raises, error goes to stderr."""
        from tube_scout.cli.collect import build_signal_handler

        bad_audit = MagicMock()
        bad_audit.append_fingerprint_row.side_effect = OSError("disk full")

        audio_temp = tmp_path / "audio_temp"
        audio_temp.mkdir()
        ref = ["test_video_001"]

        handler = build_signal_handler(audio_temp, bad_audit, ref)

        with pytest.raises(SystemExit) as exc_info:
            handler(2, None)

        assert exc_info.value.code == 130

        captured = capsys.readouterr()
        assert "audit write failed" in captured.err or "disk full" in captured.err
