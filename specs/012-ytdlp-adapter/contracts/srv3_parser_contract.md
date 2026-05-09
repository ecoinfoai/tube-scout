# Contract: `services/srv3_parser.py`

Module-level contract — yt-dlp srv3 XML → spec 010 transcript JSON. **Pure function, no I/O** (caller reads file, passes string).

## Public surface

```python
from pathlib import Path
from typing import Literal


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
            Message: "srv3 file for video <id> has no parseable segments.
            Inspect <path> for malformed XML."

    Postcondition:
        - segments[].start, segments[].end are float seconds (3 decimal places)
        - segments[].text is non-empty stripped string
        - segments are in document order (caller may sort by start if needed)
        - len(segments) >= 1 (else Srv3ParseError)
    """


def pick_priority_track(
    manual_path: Path | None,
    auto_path: Path | None,
) -> tuple[Path, Literal["ytdlp:manual", "ytdlp:auto"]] | None:
    """Pick priority subtitle track (clarify Q2 — manual 우선, auto fallback).

    Args:
        manual_path: Path to manual srv3 (yt-dlp --write-subs output), or None.
        auto_path: Path to auto srv3 (yt-dlp --write-auto-subs output), or None.

    Returns:
        Tuple of (chosen_path, source_value) — manual_path 우선.
        None if both inputs are None (caller handles "no_captions_available").

    Examples:
        >>> pick_priority_track(Path("a.ko.srv3"), Path("a.ko-orig.srv3"))
        (PosixPath("a.ko.srv3"), "ytdlp:manual")
        >>> pick_priority_track(None, Path("a.ko.srv3"))
        (PosixPath("a.ko.srv3"), "ytdlp:auto")
        >>> pick_priority_track(None, None)
        None
    """
```

## Test scenarios (RED-first)

`tests/unit/test_srv3_parser.py` — 7 시나리오:

1. **Manual srv3 (Korean lecture, 767 segments)**: spike fixture `tuxscjwiJYs.ko.srv3` (146 KB) → 767 segments, start=3.3, end=1982.3, source="ytdlp:auto" or "ytdlp:manual" 인자 그대로.
2. **`<p a="1">` rolling display skip**: fixture에 `<p t="100" d="200" a="1"><s>예고</s></p><p t="100" d="200"><s>예고</s></p>` → segments len=1 (rolling skip 검증).
3. **Empty `<p>` skip**: `<p t="100" d="200"></p><p t="300" d="100"><s>실제</s></p>` → segments len=1.
4. **`<p>` direct text (no `<s>`)**: `<p t="0" d="500">[음악]</p>` → segments[0] = {"start": 0.0, "end": 0.5, "text": "[음악]"}.
5. **Empty `<body>`**: `<timedtext><body></body></timedtext>` → raises `Srv3ParseError`.
6. **Malformed XML**: `<timedtext><body><p t="0">unclosed` → raises `Srv3ParseError`.
7. **UTF-8 한국어 정확 보존**: `<s>안녕하세요 홍길동의 교수입니다</s>` → segments[0].text == "안녕하세요 홍길동의 교수입니다" (한글 NFC 정상화 미적용 — yt-dlp 원본 그대로). 익명 placeholder 사용 — `project_public_repo_transition` 정책 적용.

`tests/unit/test_pick_priority_track.py` — 4 시나리오:

1. Both manual + auto → manual.
2. Only auto → auto.
3. Only manual → manual.
4. Both None → None.

## Boundary references

- B-X1-1: 출력 dict 가 spec 010 transcript JSON 형식과 동일 (테스트로 검증)
- Constitution III: 모든 함수 type hints + Google docstring
