# Contract: `services/ytdlp_adapter.py`

Module-level contract — yt-dlp subprocess wrapper for caption + audio fetch. **Pure I/O, no parsing logic** (parsing → `srv3_parser`, fingerprint → `audio_fingerprint`).

## Public surface

```python
from pathlib import Path
from typing import Literal

CookiesBrowser = Literal[
    "brave", "firefox", "chromium", "chrome", "edge", "opera", "vivaldi", "whale"
]


def fetch_caption_via_ytdlp(
    video_url: str,
    output_dir: Path,
    cookies_browser: CookiesBrowser | None = "brave",
    cookies_path: Path | None = None,
    sub_langs: tuple[str, ...] = ("ko", "ko-orig"),
    sleep_seconds: tuple[float, float] = (30.0, 60.0),
    timeout_seconds: float = 300.0,
) -> tuple[Path | None, Path | None]:
    """Fetch ASR/manual captions via yt-dlp.

    Calls `yt-dlp --write-subs --write-auto-subs --sub-format srv3 --sub-langs <langs>
    --skip-download --output <output_dir>/{id}.{ext}` with cookies.

    Args:
        video_url: YouTube URL (full or short form).
        output_dir: Directory to drop srv3 file(s).
        cookies_browser: Browser name for `--cookies-from-browser`. None to skip.
        cookies_path: 0600 cookies.txt path. Used as fallback if cookies_browser fails.
        sub_langs: Subtitle languages priority list (ko, ko-orig default).
        sleep_seconds: Random sleep range BEFORE the call (rate limit prevention).
        timeout_seconds: subprocess timeout. None at this point — fail-fast on hang.

    Returns:
        Tuple of (manual_srv3_path, auto_srv3_path). Either may be None.
        - Both None: video has no captions of any kind (audit "no_captions_available")
        - Only manual: yt-dlp downloaded `<id>.ko.srv3` from --write-subs
        - Only auto: yt-dlp downloaded `<id>.ko.srv3` and/or `<id>.ko-orig.srv3` from --write-auto-subs

    Raises:
        YtdlpAuthError: cookies decryption failed (Brave keyring locked, cookies expired).
            Message: "Brave keyring is locked. Run `tube-scout auth refresh-cookies`
            or set TUBE_SCOUT_COOKIES_FILE to a 0600 cookies.txt path."
        YtdlpRateLimitError: HTTP 429 after exponential backoff (60→300→1800s, 3 retries).
            Message: "YouTube rate limit hit on video <id>. Channel processing
            terminated. Resume with `tube-scout collect transcripts --channel <alias>`."
        YtdlpNetworkError: Network failure / DNS / TLS.
            Message: "Network failure fetching <video_url>. Check connectivity."
        YtdlpLiveStreamError: video is live/premiere (not finalized).
            Message: "Video <id> is a live stream or premiere; skipping. Re-run after finalization."
        subprocess.TimeoutExpired: yt-dlp hung > timeout_seconds.
    """


def fetch_audio_via_ytdlp(
    video_url: str,
    output_dir: Path,
    cookies_browser: CookiesBrowser | None = "brave",
    cookies_path: Path | None = None,
    sample_rate: int = 22050,
    audio_format: str = "mp3",
    audio_quality: str = "128K",
    sleep_seconds: tuple[float, float] = (30.0, 60.0),
    timeout_seconds: float = 600.0,
) -> Path:
    """Download audio via yt-dlp + extract.

    Calls `yt-dlp --extract-audio --audio-format mp3 --audio-quality 128K
    --postprocessor-args "ffmpeg:-ar 22050 -ac 1" --output ...` with cookies.

    Args:
        video_url, output_dir, cookies_browser, cookies_path, sleep_seconds: see above.
        sample_rate: ffmpeg `-ar` parameter (Hz). chromaprint canonical 22050.
        audio_format: yt-dlp `--audio-format`. mp3 default for chromaprint compat.
        audio_quality: yt-dlp `--audio-quality`. 128K = 128 kbps.
        timeout_seconds: subprocess timeout (longer than caption — 2hr video buffer).

    Returns:
        Path to extracted audio file (e.g., `<output_dir>/<vid>.mp3`).

    Raises (Same as `fetch_caption_via_ytdlp` plus):
        YtdlpAudioDecodeError: ffmpeg postprocessor failed (rare codec).
            Message: "Audio decode failed for <id>. Codec not supported by ffmpeg."

    Postcondition:
        - Returned file is 22050Hz mono mp3 (verified via ffprobe).
        - File path is `<output_dir>/<video_id>.mp3` (yt-dlp output template).
        - Caller MUST delete file within 60 seconds (FR-009, SC-004).
    """


def resolve_cookies_source(
    cookies_browser: str | None,
    cookies_path: Path | None,
    env: Mapping[str, str] | None = None,
) -> CookiesSource:
    """Resolve cookies source with fallback chain (R-6, FR-017).

    Resolution order:
      1. CLI flag cookies_browser → CookiesSource(kind='browser', browser=...)
      2. CLI flag cookies_path → CookiesSource(kind='file', path=...)
      3. env['TUBE_SCOUT_COOKIES_FILE'] → CookiesSource(kind='file', path=...)
      4. env['TUBE_SCOUT_COOKIES_BROWSER'] → CookiesSource(kind='browser', browser=...)
      5. Default → CookiesSource(kind='browser', browser='brave')

    On step (5) fallback to (3) implicit default path:
      - If `~/.config/tube-scout/cookies.txt` exists with 0600 perms → kind='file'
      - Else still kind='browser', brave (call-site decides keyring fallback)

    Raises:
        CookiesSourceError: env path / explicit path doesn't exist OR perms != 0600.
            Message: "Cookies file <path> has insecure permissions (expected 0600).
            Run `chmod 600 <path>` and retry."
    """
```

## Error pattern catalog

8 exception types / 24 raise sites. **All Constitution II compliant** (English, actionable, no env-var leak).

| Exception | Trigger | Actionable suffix | Audit reason value |
|---|---|---|---|
| `YtdlpAuthError` | Brave keyring locked, cookies decryption fail | "Run `tube-scout auth refresh-cookies` or set TUBE_SCOUT_COOKIES_FILE" | `cookies_expired` |
| `YtdlpRateLimitError` | HTTP 429 after 3 backoffs (60→300→1800s) | "Resume with `tube-scout collect transcripts --channel <alias>`" | `rate_limit` |
| `YtdlpNetworkError` | DNS / TLS / socket | "Check connectivity" | `network_failure` |
| `YtdlpLiveStreamError` | Live or premiere | "Re-run after finalization" | `live_or_premiere` |
| `YtdlpAudioDecodeError` | ffmpeg PP fail | "Codec not supported by ffmpeg" | `audio_decode_failed` |
| `YtdlpNoCaptionsError` | manual + auto 모두 부재 (raise 0, return (None,None) instead) | — | `no_captions_available` |
| `CookiesSourceError` | path missing / perms wrong | "Run `chmod 600 <path>`" | (CLI 단계에서 처리) |
| `subprocess.TimeoutExpired` | yt-dlp hung (>5 min caption / >10 min audio) | "yt-dlp hung; check Brave version + network" | `timeout` |

## Test scenarios (RED-first)

`tests/contract/test_ytdlp_adapter_contract.py` — 시그니처 + 반환 형식만 검증 (subprocess mock).

`tests/unit/test_ytdlp_adapter.py` — 8 시나리오:

1. `test_fetch_caption_manual_track_present`: yt-dlp stdout mock에서 `Writing video subtitles to: <vid>.ko.srv3` 1줄 → returns (manual_path, None).
2. `test_fetch_caption_only_auto_tracks`: yt-dlp stdout mock에서 `Writing video subtitles to: <vid>.ko.srv3` + `<vid>.ko-orig.srv3` (auto만) → returns (None, auto_path).
3. `test_fetch_caption_no_tracks`: yt-dlp returncode=0 + stdout 에 `subtitles` 없음 → returns (None, None) + audit "no_captions_available".
4. `test_fetch_caption_auth_fail`: yt-dlp stderr `ERROR: Failed to extract any cookies` → raises `YtdlpAuthError` with brave keyring message.
5. `test_fetch_caption_rate_limit_429`: HTTP 429 mock 3회 → `YtdlpRateLimitError` after 3 backoffs.
6. `test_fetch_audio_postprocessor_args_uses_ffmpeg_prefix`: subprocess args 검증 — `--postprocessor-args ffmpeg:-ar 22050 -ac 1` 정확.
7. `test_fetch_audio_returns_22050hz_mono_mp3`: ffprobe mock으로 sample_rate=22050, channels=1, codec=mp3 검증.
8. `test_resolve_cookies_source_priority`: 5 resolution paths (CLI > env > default) 각각 검증.

## Boundary references

- B-X1-1: srv3 파일 → `srv3_parser` 모듈로 전달, 본 모듈은 파싱 0
- B-X1-6: cookies fallback chain — `resolve_cookies_source()` 가 단일 진입점
- B-X1-7: output_dir 은 `<project>/01_collect/{transcripts,audio_temp}/`
- Constitution II: 모든 raise 사이트가 actionable English 메시지
