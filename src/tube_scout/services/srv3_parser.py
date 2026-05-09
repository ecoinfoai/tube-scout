"""srv3_parser — yt-dlp srv3 XML → spec 010 transcript JSON. Pure, no I/O."""
import datetime
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Literal


class Srv3ParseError(Exception):
    """Raised when srv3 XML is malformed or yields no usable segments."""


def srv3_to_transcript_json(
    srv3_text: str,
    video_id: str,
    language: str = "ko",
    source: Literal["ytdlp:manual", "ytdlp:auto"] = "ytdlp:auto",
) -> dict:
    """Parse yt-dlp srv3 to spec 010 transcript JSON.

    Skip rules (spike-confirmed):
      - <p a="1">: ASR rolling-display duplicate → skip
      - <p> with empty/whitespace-only text → skip
      - segment text = concat of <s> child text in document order
        (or <p> direct text if no <s> children)

    Args:
        srv3_text: srv3 file content (UTF-8 string).
        video_id: 11-char YouTube video ID.
        language: BCP-47 language code (default 'ko').
        source: 'ytdlp:manual' (from --write-subs) or 'ytdlp:auto' (--write-auto-subs).

    Returns:
        {
            "video_id": str,
            "language": str,
            "source": str,
            "fetched_at": str,  # ISO 8601 timezone-aware
            "segments": [
                {"start": float, "end": float, "text": str},
                ...
            ]
        }

    Raises:
        Srv3ParseError: malformed XML, missing <body>, no usable <p> elements.

    Postcondition:
        - segments[].start, segments[].end are float seconds (3 decimal places)
        - segments[].text is non-empty stripped string
        - segments are in document order
        - len(segments) >= 1 (else Srv3ParseError)
    """
    try:
        root = ET.fromstring(srv3_text)
    except ET.ParseError as exc:
        raise Srv3ParseError(
            f"srv3 file for video {video_id} has no parseable segments. "
            f"Inspect for malformed XML."
        ) from exc

    body = root.find("body")
    if body is None:
        raise Srv3ParseError(
            f"srv3 file for video {video_id} has no parseable segments. "
            f"Missing <body> element."
        )

    segments = []
    for p in body.iter("p"):
        if p.get("a") == "1":
            continue

        s_children = p.findall("s")
        if s_children:
            text = "".join((s.text or "") for s in s_children)
        else:
            text = p.text or ""

        text = text.strip()
        if not text:
            continue

        t_ms = int(p.get("t", "0"))
        d_ms = int(p.get("d", "0"))
        start = round(t_ms / 1000, 3)
        end = round((t_ms + d_ms) / 1000, 3)

        segments.append({"start": start, "end": end, "text": text})

    if not segments:
        raise Srv3ParseError(
            f"srv3 file for video {video_id} has no parseable segments. "
            f"Inspect for malformed XML."
        )

    fetched_at = datetime.datetime.now(tz=datetime.UTC).isoformat()

    return {
        "video_id": video_id,
        "language": language,
        "source": source,
        "fetched_at": fetched_at,
        "segments": segments,
    }


def pick_priority_track(
    manual_path: Path | None,
    auto_path: Path | None,
) -> tuple[Path, Literal["ytdlp:manual", "ytdlp:auto"]] | None:
    """Pick priority subtitle track — manual first, auto fallback.

    Args:
        manual_path: Path to manual srv3 (yt-dlp --write-subs output), or None.
        auto_path: Path to auto srv3 (yt-dlp --write-auto-subs output), or None.

    Returns:
        Tuple of (chosen_path, source_value) — manual_path preferred.
        None if both inputs are None (caller handles "no_captions_available").

    Examples:
        >>> pick_priority_track(Path("a.ko.srv3"), Path("a.ko-orig.srv3"))
        (PosixPath("a.ko.srv3"), "ytdlp:manual")
        >>> pick_priority_track(None, Path("a.ko.srv3"))
        (PosixPath("a.ko.srv3"), "ytdlp:auto")
        >>> pick_priority_track(None, None)
        None
    """
    if manual_path is not None:
        return (manual_path, "ytdlp:manual")
    if auto_path is not None:
        return (auto_path, "ytdlp:auto")
    return None
