"""yt-dlp subprocess wrapper for caption and audio fetch (spec 012).

Pure I/O adapter: no parsing logic (parsing → srv3_parser,
fingerprint → audio_fingerprint). Phase 3 will add fetch functions.
"""

import os
import stat
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from tube_scout.services.ytdlp_errors import CookiesSourceError

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
