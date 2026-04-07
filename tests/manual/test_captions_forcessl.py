"""Manual test: Captions API with youtube.force-ssl scope.

Requires browser OAuth login (new scope).
Token saved separately to avoid breaking existing auth.
"""

import json
import sys
from pathlib import Path

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from google.auth.transport.requests import Request

# force-ssl scope — required for Captions API
SCOPES = [
    "https://www.googleapis.com/auth/youtube.force-ssl",
]

TOKEN_PATH = Path.home() / ".config" / "tube-scout" / "token_forcessl.json"

PRIVATE_VIDEO_IDS = [
    "private_vid_001",  # 홍길동 2025 감염미생물학 13주차 1차시
    "private_vid_002",  # 홍길동 2025 감염미생물학 11주차 2차시
]
PUBLIC_VIDEO_ID = "public_vid_001"

import base64
import os
import tempfile


def _resolve_client_secret() -> str:
    """Resolve client secret file path.

    Checks TUBE_SCOUT_CLIENT_SECRET (file path) first,
    then TUBE_SCOUT_CLIENT_SECRET_B64 (base64 encoded JSON),
    then falls back to dotenv file.
    """
    # 1. Direct file path
    path = os.environ.get("TUBE_SCOUT_CLIENT_SECRET")
    if path and Path(path).exists():
        return path

    # 2. Base64 encoded (from agenix/.env)
    b64 = os.environ.get("TUBE_SCOUT_CLIENT_SECRET_B64")
    if not b64:
        # Try loading from dotenv manually
        env_file = Path.home() / ".config" / "tube-scout" / ".env"
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                if line.startswith("TUBE_SCOUT_CLIENT_SECRET_B64="):
                    b64 = line.split("=", 1)[1].strip().strip('"')
                    break

    if b64:
        decoded = base64.b64decode(b64)
        tmp = Path(tempfile.mktemp(suffix=".json", prefix="client_secret_"))
        tmp.write_bytes(decoded)
        return str(tmp)

    raise FileNotFoundError(
        "Cannot find client secret. Set TUBE_SCOUT_CLIENT_SECRET or "
        "TUBE_SCOUT_CLIENT_SECRET_B64."
    )


def get_credentials() -> Credentials:
    """Get or create OAuth credentials with force-ssl scope."""
    creds = None

    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        print("Refreshing token...")
        creds.refresh(Request())
    else:
        print("New OAuth login required (youtube.force-ssl scope).")
        print("Browser window will open...")
        client_secret = _resolve_client_secret()
        flow = InstalledAppFlow.from_client_secrets_file(client_secret, SCOPES)
        creds = flow.run_local_server(port=8080)

    TOKEN_PATH.write_text(creds.to_json())
    print(f"Token saved to {TOKEN_PATH}")
    return creds


def test_video(youtube, video_id: str, label: str):
    """Test captions.list and captions.download for one video."""
    print(f"\n{'='*60}")
    print(f"{label}: {video_id}")
    print(f"{'='*60}")

    # Step 1: List captions
    try:
        response = youtube.captions().list(
            part="snippet",
            videoId=video_id,
        ).execute()
        items = response.get("items", [])
        print(f"captions.list: {len(items)} track(s)")

        for item in items:
            s = item["snippet"]
            print(f"  Track: {item['id']} | lang={s['language']} | kind={s['trackKind']} | status={s.get('status','?')}")

        if not items:
            print("  No caption tracks found.")
            return

    except Exception as e:
        print(f"captions.list ERROR: {type(e).__name__}: {e}")
        return

    # Step 2: Download first track
    track = items[0]
    track_id = track["id"]
    print(f"\ncaptions.download: {track_id} (SRT format)...")

    try:
        content = youtube.captions().download(
            id=track_id,
            tfmt="srt",
        ).execute()

        text = content.decode("utf-8") if isinstance(content, bytes) else str(content)
        lines = text.strip().split("\n")
        print(f"  OK — {len(lines)} lines, {len(text)} bytes")
        print(f"  Preview:")
        for line in lines[:8]:
            print(f"    | {line}")

    except Exception as e:
        print(f"  Download ERROR: {type(e).__name__}: {e}")


def main():
    creds = get_credentials()
    print(f"Credentials valid: {creds.valid}")

    youtube = build("youtube", "v3", credentials=creds)

    # Test public video first
    test_video(youtube, PUBLIC_VIDEO_ID, "PUBLIC")

    # Test private videos
    for vid in PRIVATE_VIDEO_IDS:
        test_video(youtube, vid, "PRIVATE")

    print(f"\n{'#'*60}")
    print("DONE")


if __name__ == "__main__":
    main()
