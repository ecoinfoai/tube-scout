"""Manual test: Captions API access for private videos.

Tests whether OAuth-authenticated Captions API can:
1. List caption tracks for private videos
2. Download caption content
3. Access ASR (auto-generated) captions
"""

import sys
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

SCOPES = [
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]

# Test targets: confirmed private videos
PRIVATE_VIDEO_IDS = [
    "private_vid_001",  # 홍길동 2025 감염미생물학 13주차 1차시
    "private_vid_002",  # 홍길동 2025 감염미생물학 11주차 2차시
    "private_vid_003",  # 홍길동 2025 감염미생물학 11주차 1차시
]

# Confirmed public video (has auto caption)
PUBLIC_VIDEO_ID = "public_vid_001"  # 홍길동 2026 간호학과 인체구조와기능 4주차 2차시


def load_credentials() -> Credentials:
    """Load OAuth credentials from token file."""
    token_path = Path.home() / ".config" / "tube-scout" / "token.json"
    if not token_path.exists():
        print(f"ERROR: Token not found at {token_path}")
        sys.exit(1)

    creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    if creds.expired and creds.refresh_token:
        print("Token expired, refreshing...")
        creds.refresh(Request())
        # Save refreshed token
        token_path.write_text(creds.to_json())
        print("Token refreshed OK")

    return creds


def test_captions_list(youtube, video_id: str, label: str) -> list[dict]:
    """Test captions.list for a video."""
    print(f"\n{'='*60}")
    print(f"TEST captions.list — {label}")
    print(f"Video ID: {video_id}")
    print(f"{'='*60}")

    try:
        response = youtube.captions().list(
            part="snippet",
            videoId=video_id,
        ).execute()

        items = response.get("items", [])
        print(f"Result: {len(items)} caption track(s) found")

        for item in items:
            snippet = item["snippet"]
            print(f"  - ID: {item['id']}")
            print(f"    Language: {snippet['language']}")
            print(f"    TrackKind: {snippet['trackKind']}")
            print(f"    Name: {snippet.get('name', '(none)')}")
            print(f"    IsAutoSynced: {snippet.get('isAutoSynced', 'N/A')}")
            print(f"    Status: {snippet.get('status', 'N/A')}")

        return items

    except Exception as e:
        print(f"ERROR: {type(e).__name__}: {e}")
        return []


def test_captions_download(youtube, caption_id: str, video_id: str) -> str | None:
    """Test captions.download for a caption track."""
    print(f"\n  Downloading caption {caption_id}...")

    try:
        # Try SRT format
        response = youtube.captions().download(
            id=caption_id,
            tfmt="srt",
        ).execute()

        content = response.decode("utf-8") if isinstance(response, bytes) else response
        lines = content.strip().split("\n")
        print(f"  Download OK — {len(lines)} lines")
        print("  First 5 lines:")
        for line in lines[:5]:
            print(f"    | {line}")
        return content

    except Exception as e:
        print(f"  Download ERROR: {type(e).__name__}: {e}")
        return None


def main():
    print("Loading OAuth credentials...")
    creds = load_credentials()
    print(f"Credentials valid: {creds.valid}")

    youtube = build("youtube", "v3", credentials=creds)

    # Test 1: Public video (baseline — should work)
    print("\n" + "#" * 60)
    print("# PHASE 1: Public video (baseline)")
    print("#" * 60)
    items = test_captions_list(youtube, PUBLIC_VIDEO_ID, "PUBLIC video")
    if items:
        test_captions_download(youtube, items[0]["id"], PUBLIC_VIDEO_ID)

    # Test 2: Private videos
    print("\n" + "#" * 60)
    print("# PHASE 2: Private videos")
    print("#" * 60)
    for vid in PRIVATE_VIDEO_IDS:
        items = test_captions_list(youtube, vid, "PRIVATE video")
        if items:
            test_captions_download(youtube, items[0]["id"], vid)

    # Summary
    print("\n" + "#" * 60)
    print("# SUMMARY")
    print("#" * 60)
    print("Test complete. Review results above.")


if __name__ == "__main__":
    main()
