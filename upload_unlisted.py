"""
STEP 1 of the pipeline. Run this 8 hours before a scheduled slot time.

Picks the next unprocessed video from Drive, generates metadata with Groq,
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
import logging
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaFileUpload

from auth import get_credentials
from metadata_generator import generate_metadata
from utils import load_json, save_json

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DRIVE_FOLDER_ID = os.environ["DRIVE_FOLDER_ID"]
TIMEZONE = os.environ.get("TIMEZONE", "Asia/Kolkata")
YOUTUBE_CATEGORY_ID = os.environ.get("YOUTUBE_CATEGORY_ID", "22")  # 22 = People & Blogs

SLOT_TIMES = {
    "A": os.environ.get("SLOT_A_TIME", "17:30"),  # 5:30 PM IST default
    "B": os.environ.get("SLOT_B_TIME", "21:30"),  # 9:30 PM IST default
}

LOG_FILE = "processed_log.json"
QUEUE_FILE = "publish_queue.json"
TEMP_DIR = "temp_downloads"


# ---------------------------------------------------------------------------
# Drive helpers
# ---------------------------------------------------------------------------

def list_drive_videos(drive, folder_id: str) -> list[dict]:
    query = f"'{folder_id}' in parents and trashed = false"
    results = (
        drive.files()
        .list(q=query, fields="files(id, name, mimeType)", orderBy="name", pageSize=1000)
        .execute()
    )
    return [f for f in results.get("files", []) if f["mimeType"].startswith("video/")]


def make_shareable(drive, file_id: str) -> str:
    """Grant anyone-with-link viewer access and return a direct-download URL."""
    drive.permissions().create(
        fileId=file_id,
        body={"type": "anyone", "role": "reader"},
    ).execute()
    return f"https://drive.google.com/uc?export=download&id={file_id}"


def download_video(drive, file_id: str, filename: str) -> str:
    """Download *file_id* from Drive into TEMP_DIR and return the local path."""
    os.makedirs(TEMP_DIR, exist_ok=True)
    local_path = os.path.join(TEMP_DIR, filename)
    request = drive.files().get_media(fileId=file_id)
    with open(local_path, "wb") as fh:
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            status, done = downloader.next_chunk()
            if status:
                logger.info("  Download progress: %d%%", int(status.progress() * 100))
    return local_path


# ---------------------------------------------------------------------------
# Scheduling
# ---------------------------------------------------------------------------

def next_slot_datetime(slot: str) -> datetime:
    """Return the next occurrence of *slot*'s time in TIMEZONE (tomorrow if already past)."""
    tz = ZoneInfo(TIMEZONE)
    now = datetime.now(tz)
    hour, minute = map(int, SLOT_TIMES[slot].split(":"))
    target = datetime(now.year, now.month, now.day, hour, minute, tzinfo=tz)
    if target <= now:
        target += timedelta(days=1)
    return target


# ---------------------------------------------------------------------------
# YouTube helpers
# ---------------------------------------------------------------------------

def upload_unlisted_youtube(
    youtube, video_path: str, title: str, description: str, tags: list[str]
) -> str:
    """Upload *video_path* as an unlisted video and return the YouTube video ID."""
    body = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": tags,
            "categoryId": YOUTUBE_CATEGORY_ID,
        },
        "status": {
            "privacyStatus": "unlisted",
            "selfDeclaredMadeForKids": False,
        },
    }
    media = MediaFileUpload(video_path, chunksize=-1, resumable=True, mimetype="video/*")
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            logger.info("  Upload progress: %d%%", int(status.progress() * 100))

    return response["id"]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Queue a video for a publishing slot.")
    parser.add_argument("--slot", choices=["A", "B"], required=True, help="Publishing slot (A or B)")
    args = parser.parse_args()

    creds = get_credentials()
    drive = build("drive", "v3", credentials=creds)
    youtube = build("youtube", "v3", credentials=creds)

    log = load_json(LOG_FILE, {"processed_file_ids": []})
    queue = load_json(QUEUE_FILE, [])

    videos = list_drive_videos(drive, DRIVE_FOLDER_ID)
    next_video = next(
        (v for v in videos if v["id"] not in log["processed_file_ids"]), None
    )

    if not next_video:
        logger.info("No new videos to process.")
        return

    logger.info("Next video: %s", next_video["name"])

    logger.info("Generating metadata with Groq...")
    metadata = generate_metadata(next_video["name"])

    logger.info("Downloading from Drive...")
    local_path = download_video(drive, next_video["id"], next_video["name"])

    # Critical section: keep cleanup in finally so a partial run never leaves
    # a dangling temp file or a video stuck in limbo.
    try:
        logger.info("Uploading to YouTube as unlisted...")
        video_id = upload_unlisted_youtube(
            youtube, local_path,
            metadata["title"], metadata["description"], metadata["tags"],
        )
        logger.info("  YouTube video ID: %s", video_id)

        logger.info("Making Drive file link-shareable for Instagram...")
        drive_public_url = make_shareable(drive, next_video["id"])

        go_live_at = next_slot_datetime(args.slot)
        logger.info("Queued to go public/live at: %s", go_live_at.isoformat())

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

    finally:
        # Always clean up the temp file, even if an exception was raised above.
        if os.path.exists(local_path):
            os.remove(local_path)
            logger.debug("Removed temp file: %s", local_path)

    logger.info("Done. Video will go public on YouTube and post to Instagram at the scheduled time.")


if __name__ == "__main__":
    main()