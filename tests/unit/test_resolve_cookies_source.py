"""Unit tests for resolve_cookies_source() (spec 012, FR-002, FR-017).

T008 RED — 5 resolution chain scenarios must be tested before implementation.
"""

import stat
from pathlib import Path

import pytest


def test_cli_browser_flag_takes_priority(tmp_path):
    from tube_scout.services.ytdlp_adapter import CookiesSource, resolve_cookies_source

    result = resolve_cookies_source(
        cookies_browser="firefox",
        cookies_path=None,
        env={"TUBE_SCOUT_COOKIES_BROWSER": "chrome", "TUBE_SCOUT_COOKIES_FILE": "/tmp/c.txt"},
    )
    assert result == CookiesSource(kind="browser", browser="firefox")


def test_cli_path_flag_second_priority(tmp_path):
    from tube_scout.services.ytdlp_adapter import CookiesSource, resolve_cookies_source

    cookie_file = tmp_path / "cookies.txt"
    cookie_file.write_text("# cookies")
    cookie_file.chmod(0o600)

    result = resolve_cookies_source(
        cookies_browser=None,
        cookies_path=cookie_file,
        env={},
    )
    assert result == CookiesSource(kind="file", path=cookie_file)


def test_env_cookies_file_third_priority(tmp_path):
    from tube_scout.services.ytdlp_adapter import CookiesSource, resolve_cookies_source

    cookie_file = tmp_path / "cookies.txt"
    cookie_file.write_text("# cookies")
    cookie_file.chmod(0o600)

    result = resolve_cookies_source(
        cookies_browser=None,
        cookies_path=None,
        env={"TUBE_SCOUT_COOKIES_FILE": str(cookie_file)},
    )
    assert result == CookiesSource(kind="file", path=cookie_file)


def test_env_cookies_browser_fourth_priority():
    from tube_scout.services.ytdlp_adapter import CookiesSource, resolve_cookies_source

    result = resolve_cookies_source(
        cookies_browser=None,
        cookies_path=None,
        env={"TUBE_SCOUT_COOKIES_BROWSER": "chromium"},
    )
    assert result == CookiesSource(kind="browser", browser="chromium")


def test_default_fallback_is_brave():
    from tube_scout.services.ytdlp_adapter import CookiesSource, resolve_cookies_source

    result = resolve_cookies_source(
        cookies_browser=None,
        cookies_path=None,
        env={},
    )
    assert result == CookiesSource(kind="browser", browser="brave")


def test_insecure_file_perms_raises_cookies_source_error(tmp_path):
    from tube_scout.services.ytdlp_adapter import resolve_cookies_source
    from tube_scout.services.ytdlp_errors import CookiesSourceError

    cookie_file = tmp_path / "cookies.txt"
    cookie_file.write_text("# cookies")
    cookie_file.chmod(0o644)

    with pytest.raises(CookiesSourceError, match="0600"):
        resolve_cookies_source(
            cookies_browser=None,
            cookies_path=cookie_file,
            env={},
        )


def test_missing_file_raises_cookies_source_error(tmp_path):
    from tube_scout.services.ytdlp_adapter import resolve_cookies_source
    from tube_scout.services.ytdlp_errors import CookiesSourceError

    missing = tmp_path / "nonexistent.txt"
    with pytest.raises(CookiesSourceError, match="nonexistent"):
        resolve_cookies_source(
            cookies_browser=None,
            cookies_path=missing,
            env={},
        )
