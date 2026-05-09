"""yt-dlp subprocess wrapper for caption and audio fetch (spec 012).

Pure I/O adapter: no parsing logic (parsing → srv3_parser,
fingerprint → audio_fingerprint).
"""

import os
import random
import subprocess
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from tube_scout.services.ytdlp_errors import (
    CookiesSourceError,
    YtdlpAuthError,
    YtdlpLiveStreamError,
    YtdlpNetworkError,
    YtdlpRateLimitError,
)

CookiesBrowser = Literal[
    "brave", "firefox", "chromium", "chrome", "edge", "opera", "vivaldi", "whale"
]

_DEFAULT_COOKIES_PATH = Path.home() / ".config" / "tube-scout" / "cookies.txt"


@dataclass(frozen=True)
class CookiesSource:
    """Cookies authentication source resolution result.

    Attributes:
        kind: One of 'browser' | 'file'.
        browser: Browser name when kind == 'browser' (e.g., 'brave').
        path: File path when kind == 'file'.
    """

    kind: Literal["browser", "file"]
    browser: str | None = None
    path: Path | None = None


def _validate_cookies_file(path: Path) -> None:
    """Raise CookiesSourceError if path missing or perms != 0600."""
    if not path.exists():
        raise CookiesSourceError(
            f"Cookies file {path} does not exist. "
            "Provide a valid path with `--cookies-file` or set TUBE_SCOUT_COOKIES_FILE."
        )
    mode = path.stat().st_mode & 0o777
    if mode != 0o600:
        raise CookiesSourceError(
            f"Cookies file {path} has insecure permissions (expected 0600). "
            f"Run `chmod 600 {path}` and retry."
        )


def resolve_cookies_source(
    cookies_browser: str | None = None,
    cookies_path: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> CookiesSource:
    """Resolve cookies source with 5-step fallback chain (R-6, FR-017).

    Resolution order:
      1. CLI flag cookies_browser → CookiesSource(kind='browser', browser=...)
      2. CLI flag cookies_path → CookiesSource(kind='file', path=...)
      3. env['TUBE_SCOUT_COOKIES_FILE'] → CookiesSource(kind='file', path=...)
      4. env['TUBE_SCOUT_COOKIES_BROWSER'] → CookiesSource(kind='browser', browser=...)
      5. Default → CookiesSource(kind='browser', browser='brave')
         (auto-upgrade to file if ~/.config/tube-scout/cookies.txt exists at 0600)

    Args:
        cookies_browser: Browser name from CLI flag, or None.
        cookies_path: File path from CLI flag, or None.
        env: Environment mapping (defaults to os.environ if None).

    Returns:
        Resolved CookiesSource instance.

    Raises:
        CookiesSourceError: If an explicit/env path doesn't exist or perms != 0600.
    """
    if env is None:
        env = os.environ

    # Step 1: explicit browser CLI flag
    if cookies_browser is not None:
        return CookiesSource(kind="browser", browser=cookies_browser)

    # Step 2: explicit file CLI flag
    if cookies_path is not None:
        _validate_cookies_file(cookies_path)
        return CookiesSource(kind="file", path=cookies_path)

    # Step 3: env TUBE_SCOUT_COOKIES_FILE
    env_file = env.get("TUBE_SCOUT_COOKIES_FILE")
    if env_file:
        p = Path(env_file)
        _validate_cookies_file(p)
        return CookiesSource(kind="file", path=p)

    # Step 4: env TUBE_SCOUT_COOKIES_BROWSER
    env_browser = env.get("TUBE_SCOUT_COOKIES_BROWSER")
    if env_browser:
        return CookiesSource(kind="browser", browser=env_browser)

    # Step 5: default — brave, auto-upgrade to file if default path exists at 0600
    if _DEFAULT_COOKIES_PATH.exists():
        mode = _DEFAULT_COOKIES_PATH.stat().st_mode & 0o777
        if mode == 0o600:
            return CookiesSource(kind="file", path=_DEFAULT_COOKIES_PATH)

    return CookiesSource(kind="browser", browser="brave")


def _build_cookies_args(source: CookiesSource) -> list[str]:
    """Return yt-dlp cookie CLI args for the given CookiesSource."""
    if source.kind == "browser":
        return ["--cookies-from-browser", source.browser or "brave"]
    return ["--cookies", str(source.path)]


def _parse_ytdlp_stderr(stderr: str, video_url: str) -> None:
    """Raise typed exception if yt-dlp stderr signals a known failure."""
    lower = stderr.lower()
    if "failed to extract any cookies" in lower or "cookie" in lower and "error" in lower:
        raise YtdlpAuthError(
            "Brave keyring is locked. Run `tube-scout auth refresh-cookies` "
            "or set TUBE_SCOUT_COOKIES_FILE to a 0600 cookies.txt path."
        )
    if "429" in stderr or "too many requests" in lower:
        raise YtdlpRateLimitError(
            f"YouTube rate limit hit on video {video_url}. Channel processing "
            "terminated. Resume with `tube-scout collect transcripts --channel <alias>`."
        )
    if "live event" in lower or "premiere" in lower or "is a live stream" in lower:
        raise YtdlpLiveStreamError(
            f"Video {video_url} is a live stream or premiere; skipping. "
            "Re-run after finalization."
        )
    if "network" in lower or "dns" in lower or "tls" in lower or "connection" in lower:
        raise YtdlpNetworkError(
            f"Network failure fetching {video_url}. Check connectivity."
        )


def fetch_caption_via_ytdlp(
    video_url: str,
    output_dir: Path,
    cookies_browser: str | None = "brave",
    cookies_path: Path | None = None,
    sub_langs: tuple[str, ...] = ("ko", "ko-orig"),
    sleep_seconds: tuple[float, float] = (30.0, 60.0),
    timeout_seconds: float = 300.0,
) -> tuple[Path | None, Path | None]:
    """Fetch ASR/manual captions via yt-dlp subprocess.

    Args:
        video_url: YouTube URL (full or short form).
        output_dir: Directory to drop srv3 file(s).
        cookies_browser: Browser name for --cookies-from-browser. None to skip.
        cookies_path: 0600 cookies.txt path; used as fallback if cookies_browser fails.
        sub_langs: Subtitle languages priority list (ko, ko-orig default).
        sleep_seconds: Random sleep range BEFORE the call (rate limit prevention).
        timeout_seconds: subprocess timeout.

    Returns:
        Tuple (manual_srv3_path, auto_srv3_path). Either may be None.

    Raises:
        YtdlpAuthError: cookies decryption failed.
        YtdlpRateLimitError: HTTP 429 after exponential backoff.
        YtdlpNetworkError: network failure.
        YtdlpLiveStreamError: video is live or premiere.
        subprocess.TimeoutExpired: yt-dlp hung > timeout_seconds.
    """
    sleep_lo, sleep_hi = sleep_seconds
    if sleep_hi > 0:
        time.sleep(random.uniform(sleep_lo, sleep_hi))

    source = resolve_cookies_source(
        cookies_browser=cookies_browser,
        cookies_path=cookies_path,
    )
    cookies_args = _build_cookies_args(source)

    langs_str = ",".join(sub_langs)
    output_template = str(output_dir / "%(id)s.%(ext)s")

    cmd = [
        "yt-dlp",
        "--write-subs",
        "--write-auto-subs",
        "--sub-format", "srv3",
        "--sub-langs", langs_str,
        "--skip-download",
        "--output", output_template,
        *cookies_args,
        video_url,
    ]

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
    )

    if result.returncode != 0:
        _parse_ytdlp_stderr(result.stderr, video_url)
        raise YtdlpNetworkError(
            f"yt-dlp failed (exit {result.returncode}) fetching {video_url}. "
            "Check connectivity."
        )

    # Scan output_dir for srv3 files written in this call
    # manual: <vid>.ko.srv3 (not ko-orig)
    # auto: <vid>.ko-orig.srv3 or <vid>.ko.srv3 from --write-auto-subs
    # Heuristic: if stdout mentions a path, use it; otherwise scan dir
    manual_path: Path | None = None
    auto_path: Path | None = None

    for line in result.stdout.splitlines():
        if "Writing video subtitles to:" in line:
            raw = line.split("Writing video subtitles to:", 1)[1].strip()
            p = Path(raw)
            if p.suffix == ".srv3":
                if p.stem.endswith(".ko-orig") or p.stem.endswith("-orig"):
                    auto_path = p
                elif p.stem.endswith(".ko"):
                    manual_path = p

    # Fallback: scan output_dir for .srv3 files if stdout parsing yielded nothing
    if manual_path is None and auto_path is None:
        for p in sorted(output_dir.glob("*.srv3")):
            stem = p.stem
            if stem.endswith(".ko-orig") or stem.endswith("-orig"):
                auto_path = p
            elif stem.endswith(".ko"):
                manual_path = p

    return manual_path, auto_path
