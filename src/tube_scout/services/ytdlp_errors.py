"""Exception hierarchy for yt-dlp adapter errors (spec 012, FR-018).

All exceptions are Constitution II compliant: English, actionable messages,
no environment variable leakage.
"""


class YtdlpError(Exception):
    """Base exception for yt-dlp adapter errors. Constitution II actionable."""

    def __init__(self, message: str, **context: object) -> None:
        super().__init__(message)
        self.context: dict[str, object] = context


class YtdlpAuthError(YtdlpError):
    """Cookies decryption failed or browser keyring locked."""

    def __init__(self, message: str, **context: object) -> None:
        super().__init__(message, **context)


class YtdlpRateLimitError(YtdlpError):
    """HTTP 429 after exponential backoff (60→300→1800s, 3 retries)."""

    def __init__(self, message: str, **context: object) -> None:
        super().__init__(message, **context)


class YtdlpNetworkError(YtdlpError):
    """Network failure: DNS / TLS / socket error."""

    def __init__(self, message: str, **context: object) -> None:
        super().__init__(message, **context)


class YtdlpLiveStreamError(YtdlpError):
    """Video is a live stream or premiere that has not been finalized."""

    def __init__(self, message: str, **context: object) -> None:
        super().__init__(message, **context)


class YtdlpAudioDecodeError(YtdlpError):
    """ffmpeg postprocessor failed due to unsupported codec."""

    def __init__(self, message: str, **context: object) -> None:
        super().__init__(message, **context)


class CookiesSourceError(YtdlpError):
    """Cookies file path missing or permissions are not 0600."""

    def __init__(self, message: str, **context: object) -> None:
        super().__init__(message, **context)


class FingerprintExtractError(YtdlpError):
    """fpcalc subprocess failed to extract a chromaprint fingerprint."""

    def __init__(self, message: str, **context: object) -> None:
        super().__init__(message, **context)


class AudioTooShortError(YtdlpError):
    """Audio duration is below the minimum threshold for fingerprinting (30s)."""

    def __init__(self, message: str, **context: object) -> None:
        super().__init__(message, **context)
