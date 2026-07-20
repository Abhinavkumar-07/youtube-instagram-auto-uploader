"""
STEP 2 of the pipeline. Run this on a frequent schedule (e.g. every 10-15 min
via Task Scheduler or GitHub Actions). It checks publish_queue.json for anything
whose go_live_at time has arrived, then:

  1. Flips the YouTube video from unlisted -> public
  2. Publishes the same video to Instagram as a Reel (first time it's ever
     touched Instagram -- there's no "hold and schedule" on IG's side)
  3. Revokes the Drive file's public-link permission (no longer needed)
  4. Prunes old published entries from the queue (keeps file size bounded)

    python publish_scheduled.py
"""

import logging
import os
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
from googleapiclient.discovery import build

from auth import get_credentials
from instagram_uploader import publish_reel
from utils import load_json, save_json

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

TIMEZONE_STR = os.environ.get("TIMEZONE", "Asia/Kolkata")
QUEUE_FILE = "publish_queue.json"

# Prune published entries older than this many days to keep the queue file small
QUEUE_PRUNE_DAYS = int(os.environ.get("QUEUE_PRUNE_DAYS", "30"))


# ---------------------------------------------------------------------------
# YouTube helpers
# ---------------------------------------------------------------------------

def set_youtube_public(youtube, video_id: str) -> None:
    """Flip *video_id* from unlisted to public."""
    youtube.videos().update(
        part="status",
        body={"id": video_id, "status": {"privacyStatus": "public"}},
    ).execute()


# ---------------------------------------------------------------------------
# Drive helpers
# ---------------------------------------------------------------------------

def revoke_drive_public_access(drive, file_id: str) -> None:
    """Remove the anyone-with-link permission from a Drive file.

    The file was made public in upload_unlisted.py so Instagram could fetch it.
    Once the Reel is published we no longer need that permission.
    """
    try:
        # List permissions to find the 'anyone' permission ID
        perms = drive.permissions().list(fileId=file_id, fields="permissions(id, type)").execute()
        for perm in perms.get("permissions", []):
            if perm.get("type") == "anyone":
                drive.permissions().delete(fileId=file_id, permissionId=perm["id"]).execute()
                logger.info("  Revoked public Drive access for file %s", file_id)
                return
        logger.debug("  No public permission found for file %s (already revoked?)", file_id)
    except Exception as exc:
        # Non-fatal: log and continue. The video is already published.
        logger.warning("  Could not revoke Drive permission for %s: %s", file_id, exc)


# ---------------------------------------------------------------------------
# Queue helpers
# ---------------------------------------------------------------------------

def prune_queue(queue: list[dict]) -> list[dict]:
    """Remove published entries older than QUEUE_PRUNE_DAYS to keep file bounded."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=QUEUE_PRUNE_DAYS)
    before = len(queue)
    queue = [
        item for item in queue
        if not item.get("published")
        or datetime.fromisoformat(item["go_live_at"]) >= cutoff
    ]
    pruned = before - len(queue)
    if pruned:
        logger.info("Pruned %d old published entries from queue.", pruned)
    return queue


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    from zoneinfo import ZoneInfo

    tz = ZoneInfo(TIMEZONE_STR)
    now = datetime.now(tz)

    queue = load_json(QUEUE_FILE, [])
    due = [
        item for item in queue
        if not item.get("published")
        and datetime.fromisoformat(item["go_live_at"]) <= now
    ]

    if not due:
        logger.info("Nothing due yet.")
        return

    creds = get_credentials()
    youtube = build("youtube", "v3", credentials=creds)
    drive = build("drive", "v3", credentials=creds)

    for item in due:
        yt_id = item["youtube_video_id"]
        drive_file_id = item.get("drive_file_id")
        logger.info("Publishing slot %s video: %s", item["slot"], yt_id)

        logger.info("  Setting YouTube to public...")
        set_youtube_public(youtube, yt_id)

        logger.info("  Posting to Instagram as Reel...")
        try:
            ig_media_id = publish_reel(item["drive_public_url"], item["ig_caption"])
            logger.info("  Instagram media ID: %s", ig_media_id)
        except Exception as exc:
            logger.error(
                "  Instagram publish FAILED (YouTube still went public): %s", exc
            )
            # Continue processing other items; don't mark as published so it
            # can be retried manually.
            continue

        # Revoke Drive public access now that Instagram has fetched the video
        if drive_file_id:
            revoke_drive_public_access(drive, drive_file_id)

        item["published"] = True

    # Prune old entries and persist
    queue = prune_queue(queue)
    save_json(QUEUE_FILE, queue)
    logger.info("Done.")


if __name__ == "__main__":
    main()
