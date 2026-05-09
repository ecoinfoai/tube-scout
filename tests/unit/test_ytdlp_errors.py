"""Unit tests for ytdlp_errors exception types (spec 012, FR-018).

T006 RED — 8 exception classes must exist with correct hierarchy and
__init__ signature before any implementation.
"""

import pytest


def test_ytdlp_error_is_base_exception():
    from tube_scout.services.ytdlp_errors import YtdlpError

    err = YtdlpError("base message")
    assert isinstance(err, Exception)
    assert str(err) == "base message"


def test_ytdlp_error_accepts_context_kwargs():
    from tube_scout.services.ytdlp_errors import YtdlpError

    err = YtdlpError("msg", video_id="abc123", reason="test")
    assert str(err) == "msg"


def test_subclasses_inherit_from_ytdlp_error():
    from tube_scout.services.ytdlp_errors import (
        AudioTooShortError,
        CookiesSourceError,
        FingerprintExtractError,
        YtdlpAudioDecodeError,
        YtdlpAuthError,
        YtdlpError,
        YtdlpLiveStreamError,
        YtdlpNetworkError,
        YtdlpRateLimitError,
    )

    for cls in (
        YtdlpAuthError,
        YtdlpRateLimitError,
        YtdlpNetworkError,
        YtdlpLiveStreamError,
        YtdlpAudioDecodeError,
        CookiesSourceError,
        FingerprintExtractError,
        AudioTooShortError,
    ):
        assert issubclass(cls, YtdlpError), f"{cls.__name__} must subclass YtdlpError"


def test_each_subclass_is_catchable_as_ytdlp_error():
    from tube_scout.services.ytdlp_errors import (
        AudioTooShortError,
        CookiesSourceError,
        FingerprintExtractError,
        YtdlpAudioDecodeError,
        YtdlpAuthError,
        YtdlpError,
        YtdlpLiveStreamError,
        YtdlpNetworkError,
        YtdlpRateLimitError,
    )

    for cls in (
        YtdlpAuthError,
        YtdlpRateLimitError,
        YtdlpNetworkError,
        YtdlpLiveStreamError,
        YtdlpAudioDecodeError,
        CookiesSourceError,
        FingerprintExtractError,
        AudioTooShortError,
    ):
        with pytest.raises(YtdlpError):
            raise cls("test message")


def test_exception_message_preserved():
    from tube_scout.services.ytdlp_errors import (
        AudioTooShortError,
        CookiesSourceError,
        FingerprintExtractError,
        YtdlpAudioDecodeError,
        YtdlpAuthError,
        YtdlpLiveStreamError,
        YtdlpNetworkError,
        YtdlpRateLimitError,
    )

    for cls, msg in [
        (YtdlpAuthError, "Brave keyring is locked. Run `tube-scout auth refresh-cookies`"),
        (YtdlpRateLimitError, "YouTube rate limit hit on video abc. Resume with `tube-scout collect`"),
        (YtdlpNetworkError, "Network failure fetching https://youtu.be/abc. Check connectivity."),
        (YtdlpLiveStreamError, "Video abc is a live stream or premiere; skipping."),
        (YtdlpAudioDecodeError, "Audio decode failed for abc. Codec not supported by ffmpeg."),
        (CookiesSourceError, "Cookies file /tmp/c.txt has insecure permissions (expected 0600)."),
        (FingerprintExtractError, "fpcalc failed for abc. Check chromaprint installation."),
        (AudioTooShortError, "Video abc is too short (< 30s) for fingerprinting."),
    ]:
        err = cls(msg)
        assert str(err) == msg


def test_context_kwargs_stored():
    from tube_scout.services.ytdlp_errors import YtdlpAuthError

    err = YtdlpAuthError("auth failed", video_id="abc123", channel="ch01")
    assert err.context["video_id"] == "abc123"
    assert err.context["channel"] == "ch01"


def test_all_eight_classes_importable():
    from tube_scout.services.ytdlp_errors import (  # noqa: F401
        AudioTooShortError,
        CookiesSourceError,
        FingerprintExtractError,
        YtdlpAudioDecodeError,
        YtdlpAuthError,
        YtdlpError,
        YtdlpLiveStreamError,
        YtdlpNetworkError,
        YtdlpRateLimitError,
    )


def test_ytdlp_error_has_docstring():
    from tube_scout.services.ytdlp_errors import YtdlpError

    assert YtdlpError.__doc__ is not None
    assert len(YtdlpError.__doc__.strip()) > 0
