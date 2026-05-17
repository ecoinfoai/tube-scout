"""WAV extraction from mp4 via ffmpeg subprocess (spec 013 FR-010~FR-012)."""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


def extract_wav_16k_mono(
    mp4_path: Path,
    wav_path: Path,
    *,
    sample_rate: int = 16000,
    codec: str = "pcm_s16le",
    force: bool = False,
) -> Path:
    """Extract mono 16 kHz WAV from mp4 via ffmpeg subprocess.

    Args:
        mp4_path: Input mp4 absolute path.
        wav_path: Output wav path (parent directory must exist).
        sample_rate: Target sample rate (Hz). faster-whisper recommends 16000.
        codec: Audio codec. pcm_s16le (default) or flac.
        force: True to overwrite existing wav. False skips if wav exists.

    Returns:
        wav_path for caller convenience.

    Raises:
        FileNotFoundError: mp4_path does not exist.
        RuntimeError: ffmpeg exits with non-zero code (stderr included in message).
        subprocess.TimeoutExpired: ffmpeg hung beyond 600 seconds.
    """
    if not mp4_path.exists():
        raise FileNotFoundError(f"mp4 not found: {mp4_path}")

    if wav_path.exists() and not force:
        return wav_path

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(mp4_path),
        "-vn",
        "-ac",
        "1",
        "-ar",
        str(sample_rate),
        "-c:a",
        codec,
        str(wav_path),
    ]

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        timeout=600,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"ffmpeg failed (exit {result.returncode}): {result.stderr[:200]}"
        )

    return wav_path


def cleanup_wav(wav_path: Path, *, keep: bool = False) -> None:
    """Delete WAV unless keep=True. Safe to call when file is absent.

    Args:
        wav_path: Target path to delete.
        keep: True means no-op (maps to CLI --keep-audio).
    """
    if keep:
        return
    try:
        wav_path.unlink(missing_ok=True)
    except (PermissionError, IsADirectoryError) as exc:
        logger.warning("cleanup_wav: could not delete %s: %s", wav_path, exc)
        return


class WavLifecycle:
    """Context manager for integrated mode WAV with guaranteed cleanup.

    Usage:
        with WavLifecycle(mp4_path, wav_dir, video_id, keep=False) as wav_path:
            extract_chromaprint_fingerprint(wav_path)
            transcribe_audio(wav_path, ...)
        # __exit__ deletes wav_path unless keep=True
    """

    def __init__(
        self,
        mp4_path: Path,
        wav_dir: Path,
        video_id: str,
        *,
        keep: bool = False,
    ) -> None:
        self._mp4_path = mp4_path
        self._wav_path = wav_dir / f"{video_id}.wav"
        self._keep = keep

    def __enter__(self) -> Path:
        return self._wav_path

    def __exit__(
        self,
        exc_type: type | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        try:
            cleanup_wav(self._wav_path, keep=self._keep)
        except (PermissionError, IsADirectoryError) as exc:
            logger.warning(
                "WavLifecycle.__exit__: cleanup failed for %s: %s", self._wav_path, exc
            )
        return None
