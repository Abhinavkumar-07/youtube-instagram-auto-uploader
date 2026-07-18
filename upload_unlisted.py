"""
STEP 1 of the pipeline. Run this 8 hours before a scheduled slot time.

Picks the next unprocessed video from Drive, generates metadata with Claude,
uploads it to YouTube as UNLISTED (visible via link, not searchable), makes
the Drive file link-shareable (needed for Instagram later), and queues it
in publish_queue.json with the target public/live time.

Does NOT touch Instagram yet -- that happens in publish_scheduled.py at the
actual go-live moment, since Instagram can't be uploaded ahead and held.

    python upload_unlisted.py --slot A
    python upload_unlisted.py --slot B

Slot times are read from .env (SLOT_A_TIME, SLOT_B_TIME, daily, in TIMEZONE).
"""

import argparse
import json
import os
from datetime import datetime, timedelta

import pytz
from dotenv import load_dotenv
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaFileUpload

from metadata_generator import generate_metadata

load_dotenv()

DRIVE_FOLDER_ID = os.environ["DRIVE_FOLDER_ID"]
TIMEZONE = os.environ.get("TIMEZONE", "Asia/Kolkata")
YOUTUBE_CATEGORY_ID = os.environ.get("YOUTUBE_CATEGORY_ID", "22")  # 22 = People & Blogs (podcast-friendly)

SLOT_TIMES = {
    "A": os.environ.get("SLOT_A_TIME", "17:30"),  # 8:00 AM ET / 1:00 PM UK / 5:30 PM IST
    "B": os.environ.get("SLOT_B_TIME", "21:30"),  # 12:00 PM ET / 5:00 PM UK / 9:30 PM IST
}

TOKEN_FILE = "token.json"
LOG_FILE = "processed_log.json"
QUEUE_FILE = "publish_queue.json"
TEMP_DIR = "temp_downloads"

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


def load_json(path: str, default):
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return default


def save_json(path: str, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def list_drive_videos(drive, folder_id: str):
    query = f"'{folder_id}' in parents and trashed = false"
    results = drive.files().list(q=query, fields="files(id, name, mimeType)", orderBy="name", pageSize=1000).execute()
    return [f for f in results.get("files", []) if f["mimeType"].startswith("video/")]


def make_shareable(drive, file_id: str) -> str:
    """Grants anyone-with-link viewer access and returns a direct-download URL
    that Instagram's servers can fetch."""
    drive.permissions().create(fileId=file_id, body={"type": "anyone", "role": "reader"}).execute()
    return f"https://drive.google.com/uc?export=download&id={file_id}"


def download_video(drive, file_id: str, filename: str) -> str:
    os.makedirs(TEMP_DIR, exist_ok=True)
    local_path = os.path.join(TEMP_DIR, filename)
    request = drive.files().get_media(fileId=file_id)
    with open(local_path, "wb") as f:
        downloader = MediaIoBaseDownload(f, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
    return local_path


def next_slot_datetime(slot: str) -> datetime:
    tz = pytz.timezone(TIMEZONE)
    now = datetime.now(tz)
    hour, minute = map(int, SLOT_TIMES[slot].split(":"))
    target = tz.localize(datetime(now.year, now.month, now.day, hour, minute))
    if target <= now:
        target += timedelta(days=1)
    return target


def upload_unlisted_youtube(youtube, video_path: str, title: str, description: str, tags: list):
    body = {
        "snippet": {"title": title, "description": description, "tags": tags, "categoryId": YOUTUBE_CATEGORY_ID},
        "status": {"privacyStatus": "unlisted", "selfDeclaredMadeForKids": False},
    }
    media = MediaFileUpload(video_path, chunksize=-1, resumable=True, mimetype="video/*")
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"  Upload progress: {int(status.progress() * 100)}%")
    return response["id"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--slot", choices=["A", "B"], required=True)
    args = parser.parse_args()

    creds = get_credentials()
    drive = build("drive", "v3", credentials=creds)
    youtube = build("youtube", "v3", credentials=creds)

    log = load_json(LOG_FILE, {"processed_file_ids": []})
    queue = load_json(QUEUE_FILE, [])

    videos = list_drive_videos(drive, DRIVE_FOLDER_ID)
    next_video = next((v for v in videos if v["id"] not in log["processed_file_ids"]), None)

    if not next_video:
        print("No new videos to process.")
        return

    print(f"Next video: {next_video['name']}")

    print("Generating metadata with Groq...")
    metadata = generate_metadata(next_video["name"])

    print("Downloading from Drive...")
    local_path = download_video(drive, next_video["id"], next_video["name"])

    print("Uploading to YouTube as unlisted...")
    video_id = upload_unlisted_youtube(youtube, local_path, metadata["title"], metadata["description"], metadata["tags"])
    print(f"  YouTube video ID: {video_id}")

    print("Making Drive file link-shareable for Instagram...")
    drive_public_url = make_shareable(drive, next_video["id"])

    go_live_at = next_slot_datetime(args.slot)
    print(f"Queued to go public/live at: {go_live_at.isoformat()}")

    queue.append({
        "youtube_video_id": video_id,
        "drive_file_id": next_video["id"],
        "drive_public_url": drive_public_url,
        "ig_caption": metadata["ig_caption"],
        "go_live_at": go_live_at.isoformat(),
        "slot": args.slot,
        "published": False,
    })
    save_json(QUEUE_FILE, queue)

    log["processed_file_ids"].append(next_video["id"])
    save_json(LOG_FILE, log)

    os.remove(local_path)
    print("Done. This video will go public on YouTube and post to Instagram at the scheduled time.")


if __name__ == "__main__":
    main()