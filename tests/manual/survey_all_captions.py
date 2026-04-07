"""Full caption survey for all videos in the channel.

Strategy:
  Phase 1: youtube-transcript-api (free, no quota) for all 2550 videos
  Phase 2: Captions API (250 units/video) only for unplayable/failed ones
           Limited to daily quota budget.

Saves results incrementally to JSON for resume capability.
"""

import json
import time
from pathlib import Path

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from youtube_transcript_api import YouTubeTranscriptApi

SCOPES = ["https://www.googleapis.com/auth/youtube.force-ssl"]
TOKEN_PATH = Path.home() / ".config" / "tube-scout" / "token_forcessl.json"
CHANNEL_ID = "UCxxxxxxxxxxxxxxxxxxxxxx"
UPLOADS_PLAYLIST = "UUxxxxxxxxxxxxxxxxxxxxxx"
RESULTS_FILE = Path("/home/kjeong/localgit/tube-scout/tests/manual/caption_survey_results.json")

# Quota budget for Captions API (Phase 2)
DAILY_QUOTA = 10000
QUOTA_PER_LIST = 50
QUOTA_PER_DOWNLOAD = 200  # not used in survey, just listing
QUOTA_RESERVE = 2000  # keep some for other API calls


def load_results() -> dict:
    """Load existing results for resume."""
    if RESULTS_FILE.exists():
        return json.loads(RESULTS_FILE.read_text())
    return {"videos": {}, "phase1_done": False, "phase2_done": False}


def save_results(results: dict) -> None:
    """Save results atomically."""
    tmp = RESULTS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(results, ensure_ascii=False, indent=2))
    tmp.rename(RESULTS_FILE)


def get_youtube_client():
    """Build authenticated YouTube client."""
    creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        TOKEN_PATH.write_text(creds.to_json())
    return build("youtube", "v3", credentials=creds)


def fetch_all_video_ids(youtube) -> list[dict]:
    """Fetch all video IDs and titles from uploads playlist."""
    videos = []
    page_token = None
    while True:
        resp = youtube.playlistItems().list(
            part="snippet",
            playlistId=UPLOADS_PLAYLIST,
            maxResults=50,
            pageToken=page_token,
        ).execute()
        for item in resp.get("items", []):
            s = item["snippet"]
            vid = s["resourceId"]["videoId"]
            videos.append({
                "video_id": vid,
                "title": s.get("title", ""),
                "published_at": s.get("publishedAt", ""),
            })
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return videos


def phase1_transcript_api(results: dict, all_videos: list[dict]) -> None:
    """Phase 1: Check all videos via youtube-transcript-api (free)."""
    print(f"\n{'='*60}")
    print("PHASE 1: youtube-transcript-api (no quota cost)")
    print(f"{'='*60}")

    api = YouTubeTranscriptApi()
    total = len(all_videos)
    checked = 0
    skipped = 0

    for i, v in enumerate(all_videos):
        vid = v["video_id"]

        # Skip if already checked in phase 1
        if vid in results["videos"] and results["videos"][vid].get("phase1_checked"):
            skipped += 1
            continue

        try:
            tlist = api.list(vid)
            tracks = []
            for t in tlist:
                tracks.append({
                    "language": t.language_code,
                    "is_generated": t.is_generated,
                })
            results["videos"][vid] = {
                "title": v["title"],
                "published_at": v["published_at"],
                "phase1_checked": True,
                "phase1_status": "ok",
                "tracks": tracks,
                "has_auto": any(t["is_generated"] for t in tracks),
                "has_manual": any(not t["is_generated"] for t in tracks),
            }
        except Exception as e:
            ename = type(e).__name__
            results["videos"][vid] = {
                "title": v["title"],
                "published_at": v["published_at"],
                "phase1_checked": True,
                "phase1_status": ename,
                "tracks": [],
                "has_auto": False,
                "has_manual": False,
            }

        checked += 1

        # Progress & save every 100
        if (checked) % 100 == 0:
            save_results(results)
            ok = sum(1 for v in results["videos"].values() if v["phase1_status"] == "ok")
            fail = sum(1 for v in results["videos"].values() if v["phase1_status"] != "ok")
            print(f"  [{checked + skipped}/{total}] ok={ok} fail={fail}")

        # Small delay to avoid rate limiting
        if checked % 20 == 0:
            time.sleep(0.5)

    results["phase1_done"] = True
    save_results(results)


def phase2_captions_api(results: dict, youtube) -> None:
    """Phase 2: Check failed videos via Captions API (quota cost)."""
    failed_vids = [
        vid for vid, info in results["videos"].items()
        if info["phase1_status"] != "ok" and not info.get("phase2_checked")
    ]

    if not failed_vids:
        print("\nPhase 2: No failed videos to check.")
        return

    quota_budget = DAILY_QUOTA - QUOTA_RESERVE
    max_checks = quota_budget // QUOTA_PER_LIST

    print(f"\n{'='*60}")
    print(f"PHASE 2: Captions API (quota cost)")
    print(f"Failed videos: {len(failed_vids)}")
    print(f"Quota budget: {quota_budget} units → max {max_checks} checks")
    print(f"Will check: {min(len(failed_vids), max_checks)} videos")
    print(f"{'='*60}")

    checked = 0
    for vid in failed_vids:
        if checked >= max_checks:
            print(f"\n  Quota budget reached. {len(failed_vids) - checked} remaining for next run.")
            break

        try:
            resp = youtube.captions().list(
                part="snippet",
                videoId=vid,
            ).execute()

            items = resp.get("items", [])
            tracks = []
            for item in items:
                s = item["snippet"]
                tracks.append({
                    "language": s["language"],
                    "kind": s["trackKind"],
                    "caption_id": item["id"],
                })

            info = results["videos"][vid]
            info["phase2_checked"] = True
            info["phase2_status"] = "ok"
            info["phase2_tracks"] = tracks
            info["has_auto"] = any(t["kind"] == "asr" for t in tracks)
            info["has_manual"] = any(t["kind"] == "standard" for t in tracks)

        except Exception as e:
            info = results["videos"][vid]
            info["phase2_checked"] = True
            info["phase2_status"] = f"{type(e).__name__}: {str(e)[:100]}"

        checked += 1
        if checked % 50 == 0:
            save_results(results)
            print(f"  [{checked}/{min(len(failed_vids), max_checks)}]")

        time.sleep(0.2)  # Rate limiting

    results["phase2_done"] = (checked >= len(failed_vids))
    save_results(results)


def print_summary(results: dict) -> None:
    """Print final summary."""
    videos = results["videos"]
    total = len(videos)

    # Phase 1 results
    p1_ok = sum(1 for v in videos.values() if v["phase1_status"] == "ok")
    p1_fail = sum(1 for v in videos.values() if v["phase1_status"] != "ok")

    # Caption availability (combined phases)
    has_auto = sum(1 for v in videos.values() if v.get("has_auto"))
    has_manual = sum(1 for v in videos.values() if v.get("has_manual"))
    no_caption = sum(1 for v in videos.values() if not v.get("has_auto") and not v.get("has_manual"))

    # Phase 2 results
    p2_checked = sum(1 for v in videos.values() if v.get("phase2_checked"))
    p2_ok = sum(1 for v in videos.values() if v.get("phase2_status") == "ok")
    p2_has_caption = sum(1 for v in videos.values() if v.get("phase2_checked") and v.get("has_auto"))

    # Error breakdown
    errors = {}
    for v in videos.values():
        if v["phase1_status"] != "ok" and not v.get("phase2_checked"):
            err = v["phase1_status"]
            errors[err] = errors.get(err, 0) + 1

    print(f"\n{'#'*60}")
    print(f"CAPTION SURVEY SUMMARY")
    print(f"{'#'*60}")
    print(f"\nTotal videos: {total}")
    print(f"\n--- Phase 1 (youtube-transcript-api, free) ---")
    print(f"  Accessible: {p1_ok} ({p1_ok/total*100:.1f}%)")
    print(f"  Failed:     {p1_fail} ({p1_fail/total*100:.1f}%)")
    print(f"\n--- Phase 2 (Captions API, OAuth) ---")
    print(f"  Checked:    {p2_checked}")
    print(f"  Has caption: {p2_has_caption}")
    print(f"\n--- Combined caption availability ---")
    print(f"  Auto caption (ASR):  {has_auto} ({has_auto/total*100:.1f}%)")
    print(f"  Manual caption:      {has_manual} ({has_manual/total*100:.1f}%)")
    print(f"  No caption found:    {no_caption} ({no_caption/total*100:.1f}%)")

    if errors:
        print(f"\n--- Unchecked errors (Phase 2 pending) ---")
        for err, count in sorted(errors.items(), key=lambda x: -x[1]):
            print(f"  {err}: {count}")

    print(f"\nResults saved to: {RESULTS_FILE}")


def main():
    print("Caption Survey — Full Channel Scan")
    print(f"Channel: {CHANNEL_ID}")

    results = load_results()
    youtube = get_youtube_client()

    # Fetch all video IDs
    print("\nFetching all video IDs from channel...")
    all_videos = fetch_all_video_ids(youtube)
    print(f"Found {len(all_videos)} videos")

    # Phase 1
    if not results.get("phase1_done"):
        phase1_transcript_api(results, all_videos)
    else:
        print("\nPhase 1 already complete, skipping.")

    # Phase 2
    phase2_captions_api(results, youtube)

    # Summary
    print_summary(results)


if __name__ == "__main__":
    main()
