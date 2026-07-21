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

import logging
import os
import time

import requests
from dotenv import load_dotenv

from utils import retry_on_transient

load_dotenv()

logger = logging.getLogger(__name__)

GRAPH_API_VERSION = "v21.0"
BASE_URL = f"https://graph.facebook.com/{GRAPH_API_VERSION}"

IG_USER_ID = os.environ.get("IG_BUSINESS_ACCOUNT_ID", "").strip()
ACCESS_TOKEN = os.environ.get("META_ACCESS_TOKEN", "").strip()
# Bearer auth header — keeps the token out of POST bodies (and server logs)
_AUTH_HEADERS = {"Authorization": f"Bearer {ACCESS_TOKEN}"}

_POLL_INTERVAL_SECONDS = 10
_MAX_POLL_ATTEMPTS = 30  # 5 minutes max


@retry_on_transient(max_attempts=3, base_delay=5.0)
def _create_container(video_public_url: str, caption: str) -> str:
    """Step 1: create the media container and return its ID."""
    resp = requests.post(
        f"{BASE_URL}/{IG_USER_ID}/media",
        json={
            "media_type": "REELS",
            "video_url": video_public_url,
            "caption": caption,
        },
        headers=_AUTH_HEADERS,
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["id"]


@retry_on_transient(max_attempts=3, base_delay=5.0)
def _get_container_status(container_id: str) -> str:
    """Return the current status_code for a media container."""
    resp = requests.get(
        f"{BASE_URL}/{container_id}",
        params={"fields": "status_code"},
        headers=_AUTH_HEADERS,
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json().get("status_code", "UNKNOWN")


@retry_on_transient(max_attempts=3, base_delay=5.0)
def _publish_container(container_id: str) -> str:
    """Step 3: publish the container and return the published media ID."""
    resp = requests.post(
        f"{BASE_URL}/{IG_USER_ID}/media_publish",
        json={"creation_id": container_id},
        headers=_AUTH_HEADERS,
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["id"]


def publish_reel(video_public_url: str, caption: str) -> str:
    """Upload and publish a Reel. Returns the published media ID.

    Args:
        video_public_url: a publicly accessible URL Instagram's servers can fetch.
        caption: the Instagram caption including hashtags.

    Raises:
        ValueError: if required env vars are missing.
        RuntimeError: if Instagram reports a processing error.
        TimeoutError: if processing takes longer than ~5 minutes.
        requests.HTTPError: on unrecoverable API errors (after retries).
    """
    if not IG_USER_ID or not ACCESS_TOKEN:
        raise ValueError(
            "IG_BUSINESS_ACCOUNT_ID and META_ACCESS_TOKEN must be set in .env"
        )

    # Step 1: create container
    logger.info("  Creating Instagram media container...")
    container_id = _create_container(video_public_url, caption)
    logger.info("  Container ID: %s", container_id)

    # Step 2: poll until Instagram finishes processing
    logger.info("  Waiting for Instagram to process video...")
    for attempt in range(_MAX_POLL_ATTEMPTS):
        status = _get_container_status(container_id)

        if status == "FINISHED":
            logger.info("  Processing complete after ~%ds.", attempt * _POLL_INTERVAL_SECONDS)
            break
        if status == "ERROR":
            raise RuntimeError(
                f"Instagram failed to process video (container {container_id}). "
                "Check the video format — Instagram Reels require H.264/AAC MP4, "
                "9:16 or 1:1 aspect ratio, 3-90 seconds."
            )

        logger.debug("  Status: %s (attempt %d/%d)", status, attempt + 1, _MAX_POLL_ATTEMPTS)
        time.sleep(_POLL_INTERVAL_SECONDS)
    else:
        raise TimeoutError(
            f"Instagram video processing timed out after "
            f"{_MAX_POLL_ATTEMPTS * _POLL_INTERVAL_SECONDS}s (container {container_id})."
        )

    # Step 3: publish
    logger.info("  Publishing Reel...")
    media_id = _publish_container(container_id)
    logger.info("  Reel published. Media ID: %s", media_id)
    return media_id
