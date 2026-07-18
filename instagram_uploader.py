"""
Publishes a video (Reel) to Instagram via the Meta Graph API.

Instagram's Content Publishing API requires the video to be reachable at a
PUBLIC URL (it fetches it server-side) -- you can't POST the file directly
like YouTube. We use the Google Drive shareable link for this.

Two-step process:
  1. Create a media container (POST /{ig-user-id}/media)
  2. Poll until Instagram finishes processing the video
  3. Publish the container (POST /{ig-user-id}/media_publish)

Instagram has NO native "publish at a future time" option via API -- calling
media_publish makes it go live immediately. That's why publish_scheduled.py
calls this function exactly when it's time to go live, rather than ahead of time.
"""

import os
import time
import requests

GRAPH_API_VERSION = "v21.0"
BASE_URL = f"https://graph.facebook.com/{GRAPH_API_VERSION}"

IG_USER_ID = os.environ.get("IG_BUSINESS_ACCOUNT_ID", "")
ACCESS_TOKEN = os.environ.get("META_ACCESS_TOKEN", "")


def publish_reel(video_public_url: str, caption: str) -> str:
    """Uploads and publishes a Reel. Returns the published media ID."""
    if not IG_USER_ID or not ACCESS_TOKEN:
        raise ValueError("IG_BUSINESS_ACCOUNT_ID and META_ACCESS_TOKEN must be set in .env")

    # Step 1: create container
    create_resp = requests.post(
        f"{BASE_URL}/{IG_USER_ID}/media",
        data={
            "media_type": "REELS",
            "video_url": video_public_url,
            "caption": caption,
            "access_token": ACCESS_TOKEN,
        },
    )
    create_resp.raise_for_status()
    container_id = create_resp.json()["id"]

    # Step 2: poll until Instagram has finished processing the video
    max_attempts = 30
    for attempt in range(max_attempts):
        status_resp = requests.get(
            f"{BASE_URL}/{container_id}",
            params={"fields": "status_code", "access_token": ACCESS_TOKEN},
        )
        status_resp.raise_for_status()
        status = status_resp.json().get("status_code")

        if status == "FINISHED":
            break
        if status == "ERROR":
            raise RuntimeError(f"Instagram failed to process video: container {container_id}")

        time.sleep(10)
    else:
        raise TimeoutError("Instagram video processing did not finish in time.")

    # Step 3: publish
    publish_resp = requests.post(
        f"{BASE_URL}/{IG_USER_ID}/media_publish",
        data={"creation_id": container_id, "access_token": ACCESS_TOKEN},
    )
    publish_resp.raise_for_status()
    return publish_resp.json()["id"]
