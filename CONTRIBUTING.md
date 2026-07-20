# Contributing

Thanks for your interest! Pull requests, bug reports, and feature suggestions are welcome.

## Architecture overview

```
auth.py               — shared Google OAuth credentials helper (SCOPES, get_credentials)
utils.py              — shared JSON I/O helpers + retry_on_transient decorator
metadata_generator.py — calls Groq to produce YouTube title/description/tags + IG caption
upload_unlisted.py    — STEP 1: picks next Drive video, generates metadata, uploads unlisted to YouTube, queues for later
publish_scheduled.py  — STEP 2: at go-live time flips YouTube public, posts to Instagram, revokes Drive public link
instagram_uploader.py — thin wrapper around Meta Graph API for publishing Reels
oauth_setup.py        — one-time browser-based Google OAuth flow
```

## Setting up for local development

### 1. Clone and create a virtual environment

```bash
git clone https://github.com/Abhinavkumar-07/youtube-instagram-auto-uploader
cd youtube-instagram-auto-uploader
python -m venv venv
# Windows
venv\Scripts\activate
# macOS/Linux
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure credentials

```bash
cp .env.example .env
# Edit .env and fill in DRIVE_FOLDER_ID, GROQ_API_KEY, META_ACCESS_TOKEN,
# and IG_BUSINESS_ACCOUNT_ID. Leave slots at defaults to start.
```

Then place your `client_secret.json` in the project root and run:

```bash
python oauth_setup.py
```

### 3. Testing without real credentials (mocking)

You can test the pipeline without making real API calls by monkey-patching the
service builders in a quick scratch script:

```python
# scratch_test.py  —  run with: python scratch_test.py
from unittest.mock import MagicMock, patch
import json

# ---- Mock Drive: one video in the folder ----
fake_file = {"id": "FAKE_ID", "name": "test_clip.mp4", "mimeType": "video/mp4"}
mock_drive = MagicMock()
mock_drive.files().list().execute.return_value = {"files": [fake_file]}
mock_drive.files().get_media.return_value = MagicMock()
mock_drive.permissions().create().execute.return_value = {}

# ---- Mock YouTube: returns a fake video ID ----
mock_youtube = MagicMock()
mock_youtube.videos().insert().next_chunk.side_effect = [
    (None, {"id": "YT_FAKE_ID"}),
]

# ---- Mock Groq metadata ----
fake_metadata = {
    "title": "Test Title",
    "description": "A test description. #test",
    "tags": ["test", "video"],
    "ig_caption": "Test caption #reels",
}

with patch("upload_unlisted.get_credentials", return_value=MagicMock()), \
     patch("upload_unlisted.build", side_effect=[mock_drive, mock_youtube]), \
     patch("upload_unlisted.generate_metadata", return_value=fake_metadata), \
     patch("upload_unlisted.download_video", return_value="/tmp/fake.mp4"), \
     patch("os.path.exists", return_value=True), \
     patch("os.remove"):
    import sys
    sys.argv = ["upload_unlisted.py", "--slot", "A"]
    import upload_unlisted
    upload_unlisted.main()

print("Done — check processed_log.json and publish_queue.json")
```

Run with: `python scratch_test.py`

### 4. Testing `publish_scheduled.py` locally

Manually add an entry to `publish_queue.json` with a `go_live_at` time in the past:

```json
[
  {
    "youtube_video_id": "TEST_YT_ID",
    "drive_file_id": "TEST_DRIVE_ID",
    "drive_public_url": "https://drive.google.com/uc?export=download&id=TEST_DRIVE_ID",
    "ig_caption": "Test caption #reels",
    "go_live_at": "2024-01-01T00:00:00+05:30",
    "slot": "A",
    "published": false
  }
]
```

Then run `python publish_scheduled.py` (with real credentials, or mock similarly to above).

## Submitting changes

1. Fork the repo and create a feature branch (`git checkout -b feature/my-fix`)
2. Make your changes with clear commit messages
3. Open a pull request against `main` — describe what changed and why

## Environment variables reference

See `.env.example` for the full list with descriptions.
