"""KB-ingestible transcript export service (FR-040~FR-042)."""
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from tube_scout.models.content import VideoMetadata
from tube_scout.services.progress_reporter import ProgressReporter

ExportFormat = Literal["txt", "md", "jsonl"]

_FILLER_PATTERNS = [
    r"\b음+[~ㅡ]*\b",
    r"\b어+\b",
    r"\b에+\b",
    r"\b아+\b",
    r"\b그러니까\b",
    r"\b그래서\b",
]
_FILLER_RE = re.compile("|".join(_FILLER_PATTERNS))


class ExportResult(BaseModel):
    """Result of a single transcript export."""

    output_path: Path
    byte_count: int
    format_: str
    segment_count: int


class BulkExportResult(BaseModel):
    """Result of a bulk transcript export run."""

    output_dir: Path
    total_videos: int
    exported_count: int
    skipped_count: int
    failed_count: int
    format_: str


def _seconds_to_hms(seconds: float) -> str:
    s = int(seconds)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{sec:02d}"


def _clean_text(text: str) -> str:
    cleaned = _FILLER_RE.sub("", text)
    return re.sub(r" {2,}", " ", cleaned).strip()


def _write_txt(
    segments: list[dict],
    keep_timestamps: bool,
    clean_fillers: bool,
) -> str:
    lines: list[str] = []
    for seg in segments:
        text = _clean_text(seg["text"]) if clean_fillers else seg["text"]
        if not text:
            continue
        if keep_timestamps:
            ts = _seconds_to_hms(seg.get("start", 0.0))
            lines.append(f"[{ts}] {text}")
        else:
            lines.append(text)
    return "\n".join(lines)


def _write_md(
    segments: list[dict],
    keep_timestamps: bool,
    clean_fillers: bool,
    with_meta: bool,
    video_meta: VideoMetadata | None,
) -> str:
    parts: list[str] = []
    if with_meta and video_meta is not None:
        parts.append(f"# {video_meta.title}")
        parts.append("")
        parts.append(f"- video_id: {video_meta.video_id}")
        if video_meta.duration_seconds is not None:
            parts.append(f"- duration: {video_meta.duration_seconds}s")
        parts.append(f"- privacy_status: {video_meta.privacy_status or 'unknown'}")
        parts.append("")
        parts.append("---")
        parts.append("")

    for seg in segments:
        text = _clean_text(seg["text"]) if clean_fillers else seg["text"]
        if not text:
            continue
        if keep_timestamps:
            ts = _seconds_to_hms(seg.get("start", 0.0))
            parts.append(f"[{ts}] {text}")
        else:
            parts.append(text)
        parts.append("")

    return "\n".join(parts).rstrip() + "\n"


def _write_jsonl(
    segments: list[dict],
    keep_timestamps: bool,
    clean_fillers: bool,
    with_meta: bool,
    video_meta: VideoMetadata | None,
) -> str:
    lines: list[str] = []
    if with_meta and video_meta is not None:
        meta_obj: dict = {
            "_meta": True,
            "video_id": video_meta.video_id,
            "title": video_meta.title,
        }
        if video_meta.duration_seconds is not None:
            meta_obj["duration"] = video_meta.duration_seconds
        lines.append(json.dumps(meta_obj, ensure_ascii=False))

    for seg in segments:
        text = _clean_text(seg["text"]) if clean_fillers else seg["text"]
        obj: dict = {}
        if keep_timestamps:
            if "start" in seg:
                obj["start"] = seg["start"]
            if "end" in seg:
                obj["end"] = seg["end"]
        obj["text"] = text
        lines.append(json.dumps(obj, ensure_ascii=False))

    return "\n".join(lines) + "\n"


def _atomic_write(output_path: Path, content: str) -> int:
    """Write content atomically via tempfile+rename; return byte count."""
    parent = output_path.parent
    fd, tmp_name = tempfile.mkstemp(dir=parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp_name, output_path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
    return output_path.stat().st_size


def export_transcript(
    transcript_json_path: Path,
    output_path: Path,
    *,
    format_: ExportFormat = "txt",
    keep_timestamps: bool = False,
    clean_fillers: bool = False,
    with_meta: bool = False,
    video_meta: VideoMetadata | None = None,
) -> ExportResult:
    """Export single transcript JSON to operator's KB-ingestible plain text.

    Args:
        transcript_json_path: Path to transcript JSON file.
        output_path: Destination file path (caller must ensure parent exists).
        format_: Output format — 'txt', 'md', or 'jsonl'.
        keep_timestamps: Include [HH:MM:SS] timestamps in txt/md, start/end in jsonl.
        clean_fillers: Remove Korean ASR filler expressions.
        with_meta: Include video metadata header in md/jsonl output.
        video_meta: Required when with_meta=True.

    Returns:
        ExportResult with output_path, byte_count, format_, segment_count.

    Raises:
        FileNotFoundError: transcript_json_path does not exist.
        ValueError: with_meta=True but video_meta is None.
    """
    if not transcript_json_path.exists():
        raise FileNotFoundError(f"Transcript not found: {transcript_json_path}")
    if with_meta and video_meta is None:
        raise ValueError("video_meta is required when with_meta=True")

    data = json.loads(transcript_json_path.read_text(encoding="utf-8"))
    segments: list[dict] = data.get("segments", [])

    if format_ == "txt":
        content = _write_txt(segments, keep_timestamps, clean_fillers)
    elif format_ == "md":
        content = _write_md(segments, keep_timestamps, clean_fillers, with_meta, video_meta)
    elif format_ == "jsonl":
        content = _write_jsonl(segments, keep_timestamps, clean_fillers, with_meta, video_meta)
    else:
        raise ValueError(f"Unknown format: {format_!r}")

    byte_count = _atomic_write(output_path, content)

    return ExportResult(
        output_path=output_path,
        byte_count=byte_count,
        format_=format_,
        segment_count=len(segments),
    )


def export_bulk(
    transcripts_dir: Path,
    output_dir: Path,
    *,
    video_ids: list[str] | None = None,
    format_: ExportFormat = "txt",
    keep_timestamps: bool = False,
    clean_fillers: bool = False,
    with_meta: bool = False,
    video_meta_map: dict[str, VideoMetadata] | None = None,
    progress: ProgressReporter | None = None,
) -> BulkExportResult:
    """Export multiple transcripts to output_dir, one file per video.

    Args:
        transcripts_dir: Directory containing <video_id>.json transcript files.
        output_dir: Destination directory (must exist).
        video_ids: Explicit list of IDs to export; None scans transcripts_dir.
        format_: Output format — 'txt', 'md', or 'jsonl'.
        keep_timestamps: Pass-through to export_transcript.
        clean_fillers: Pass-through to export_transcript.
        with_meta: Pass-through to export_transcript.
        video_meta_map: Keyed by video_id; used when with_meta=True.
        progress: Optional ProgressReporter for bulk progress tracking.

    Returns:
        BulkExportResult with counts and output_dir.
    """
    if video_ids is None:
        json_files = list(transcripts_dir.glob("*.json"))
        ids = [f.stem for f in json_files]
    else:
        ids = list(video_ids)

    total = len(ids)
    exported = 0
    skipped = 0
    failed = 0

    for i, vid in enumerate(ids, start=1):
        src = transcripts_dir / f"{vid}.json"
        if not src.exists():
            skipped += 1
            continue

        vm = (video_meta_map or {}).get(vid)
        dst = output_dir / f"{vid}.{format_}"

        try:
            export_transcript(
                src,
                dst,
                format_=format_,
                keep_timestamps=keep_timestamps,
                clean_fillers=clean_fillers,
                with_meta=with_meta,
                video_meta=vm,
            )
            exported += 1
        except Exception:
            failed += 1

        if progress is not None:
            progress.update(vid, i)

    return BulkExportResult(
        output_dir=output_dir,
        total_videos=total,
        exported_count=exported,
        skipped_count=skipped,
        failed_count=failed,
        format_=format_,
    )
