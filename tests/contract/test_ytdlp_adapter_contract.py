"""Contract tests for yt-dlp adapter cross-spec boundaries (spec 012).

T014 — Verifies public surface signatures for 4 functions via inspect.signature.
Phase 3 implementations will turn these from import-fail RED to GREEN.
"""

import inspect


def test_fetch_caption_via_ytdlp_signature():
    from tube_scout.services.ytdlp_adapter import fetch_caption_via_ytdlp

    sig = inspect.signature(fetch_caption_via_ytdlp)
    params = sig.parameters

    assert "video_url" in params
    assert "output_dir" in params
    assert "cookies_browser" in params
    assert "cookies_path" in params
    assert "sub_langs" in params
    assert "sleep_seconds" in params
    assert "timeout_seconds" in params

    assert params["cookies_browser"].default == "brave"
    assert params["cookies_path"].default is None
    assert params["sub_langs"].default == ("ko", "ko-orig")


def test_fetch_audio_via_ytdlp_signature():
    from tube_scout.services.ytdlp_adapter import fetch_audio_via_ytdlp

    sig = inspect.signature(fetch_audio_via_ytdlp)
    params = sig.parameters

    assert "video_url" in params
    assert "output_dir" in params
    assert "cookies_browser" in params
    assert "cookies_path" in params
    assert "sample_rate" in params
    assert "audio_format" in params
    assert "audio_quality" in params
    assert "sleep_seconds" in params
    assert "timeout_seconds" in params

    assert params["sample_rate"].default == 22050
    assert params["audio_format"].default == "mp3"
    assert params["audio_quality"].default == "128K"


def test_resolve_cookies_source_signature():
    from tube_scout.services.ytdlp_adapter import resolve_cookies_source

    sig = inspect.signature(resolve_cookies_source)
    params = sig.parameters

    assert "cookies_browser" in params
    assert "cookies_path" in params
    assert "env" in params

    assert params["cookies_browser"].default is None
    assert params["cookies_path"].default is None
    assert params["env"].default is None


def test_extract_chromaprint_fingerprint_signature():
    from tube_scout.services.audio_fingerprint import extract_chromaprint_fingerprint

    sig = inspect.signature(extract_chromaprint_fingerprint)
    params = sig.parameters

    assert "audio_path" in params
    assert "length_seconds" in params
    assert "timeout_seconds" in params

    assert params["length_seconds"].default == 0
    assert params["timeout_seconds"].default == 60.0
