"""
STEP 2 of the pipeline. Run this on a frequent schedule (e.g. every 10-15 min
via Task Scheduler). It checks publish_queue.json for anything whose
go_live_at time has arrived, then:

  1. Flips the YouTube video from unlisted -> public
  2. Publishes the same video to Instagram as a Reel (first time it's ever
     touched Instagram -- there's no "hold and schedule" on IG's side)

    python publish_scheduled.py
"""

import json
import os
from datetime import datetime

import pytz
from dotenv import load_dotenv
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from instagram_uploader import publish_reel

load_dotenv()

TIMEZONE = os.environ.get("TIMEZONE", "Asia/Kolkata")
TOKEN_FILE = "token.json"
QUEUE_FILE = "publish_queue.json"

SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
]


def get_credentials():
    creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    if creds.expired and creds.refresh_token:
        from google.auth.transport.requests import Request

        creds.refresh(Request())
        with open(TOKEN_FILE, "w") as f:
            f.write(creds.to_json())
    return creds


def load_queue():
    if os.path.exists(QUEUE_FILE):
        with open(QUEUE_FILE) as f:
            return json.load(f)
    return []


def save_queue(queue):
    with open(QUEUE_FILE, "w") as f:
        json.dump(queue, f, indent=2)


def set_youtube_public(youtube, video_id: str):
    youtube.videos().update(
        part="status",
        body={"id": video_id, "status": {"privacyStatus": "public"}},
    ).execute()


def main():
    tz = pytz.timezone(TIMEZONE)
    now = datetime.now(tz)

    queue = load_queue()
    due = [item for item in queue if not item["published"] and datetime.fromisoformat(item["go_live_at"]) <= now]

    if not due:
        print("Nothing due yet.")
        return

    creds = get_credentials()
    youtube = build("youtube", "v3", credentials=creds)

    for item in due:
        print(f"Publishing slot {item['slot']} video: {item['youtube_video_id']}")

        print("  Setting YouTube to public...")
        set_youtube_public(youtube, item["youtube_video_id"])

        print("  Posting to Instagram as Reel...")
        try:
            ig_media_id = publish_reel(item["drive_public_url"], item["ig_caption"])
            print(f"  Instagram media ID: {ig_media_id}")
        except Exception as e:
            print(f"  Instagram publish failed (YouTube still went public): {e}")

        item["published"] = True

    save_queue(queue)
    print("Done.")


if __name__ == "__main__":
    main()
