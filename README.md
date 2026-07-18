# Drive → YouTube + Instagram Auto-Publish Pipeline

Podcast clips sit in a Google Drive folder. This pipeline picks them one at a
time, generates title/description/tags/caption with Groq, and publishes to
**YouTube (unlisted → public)** and **Instagram Reels** at the same moment,
twice a day.

## Why two scripts

YouTube's `publishAt` scheduling only works if the video is `private` at
upload time — it doesn't support "unlisted + auto-publish later." Instagram
has no scheduling in its API at all — calling publish makes it go live
immediately. So the pipeline is split in two:

| Script | Runs | Does |
|---|---|---|
| `upload_unlisted.py` | 8 hours before a slot | Picks next video, generates metadata, uploads to YouTube as **unlisted** |
| `publish_scheduled.py` | Every 10-15 min (checks the clock) | At the exact slot time: flips YouTube to **public** AND posts the same video to **Instagram Reels** |

This gives you: video sits unlisted (link-shareable, not searchable) for 8
hours, then goes public on YouTube and drops on Instagram simultaneously.

## Default daily slots (edit in `.env`)

- **Slot A: 5:30 PM IST** = 8:00 AM ET = 1:00 PM UK — US morning commute, UK lunch
- **Slot B: 9:30 PM IST** = 12:00 PM ET = 5:00 PM UK — US lunch, UK evening commute

That's 2 videos/day, published simultaneously to both platforms.

## One-time setup

### 1. Google Cloud project (Drive + YouTube)

1. https://console.cloud.google.com/ → new project.
2. Enable **Google Drive API** and **YouTube Data API v3**.
3. OAuth consent screen: External, add yourself as a test user.
4. Create OAuth Client ID (Desktop app), download JSON as `client_secret.json` in this folder.

### 2. Meta / Instagram setup

Instagram's API requires a Business or Creator account linked to a Facebook Page.

1. Create a Facebook account if you don't have one: https://www.facebook.com/
2. Create a Facebook Page (any name/category is fine — it just needs to exist): https://www.facebook.com/pages/create
3. On Instagram: Settings → Account type → switch to **Professional account** →
   choose **Creator** or **Business** → link it to the Page you just made.
4. Go to https://developers.facebook.com/ → create an app (type: **Business**).
5. In the app, add the **Instagram Graph API** product.
6. Use the **Graph API Explorer** (developers.facebook.com/tools/explorer) to:
   - Select your app, generate a **User Access Token** with `instagram_basic`,
     `instagram_content_publish`, and `pages_show_list` permissions.
   - Exchange it for a **long-lived token** (60 days) — the Explorer has a button
     for this, or use the `/oauth/access_token` endpoint with `grant_type=fb_exchange_token`.
   - Find your **Instagram Business Account ID**: call `GET /me/accounts` to get your
     Page ID, then `GET /{page-id}?fields=instagram_business_account`.
7. Put both values in `.env` as `META_ACCESS_TOKEN` and `IG_BUSINESS_ACCOUNT_ID`.

Note: long-lived tokens expire after 60 days — you'll need to refresh it
periodically (a reminder on your calendar is easiest; a token-refresh script
can be added later if this becomes a hassle).

### 3. Python environment

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

### 4. Authenticate Google (one-time, opens a browser)

```bash
python oauth_setup.py
```

### 5. Configure

Copy `.env.example` to `.env` and fill in:
- `DRIVE_FOLDER_ID`
- `GROQ_API_KEY`
- `SLOT_A_TIME` / `SLOT_B_TIME` (defaults already set)
- `META_ACCESS_TOKEN` / `IG_BUSINESS_ACCOUNT_ID`

### 6. Run

Queue a video for slot A (run this ~8 hours before 5:30 PM IST, e.g. 9:30 AM):
```bash
python upload_unlisted.py --slot A
```

Queue a video for slot B (run ~8 hours before 9:30 PM IST, e.g. 1:30 PM):
```bash
python upload_unlisted.py --slot B
```

Then keep this running on a schedule so queued videos actually go live:
```bash
python publish_scheduled.py
```

## Automating: runs in the cloud via GitHub Actions (no laptop needed)

This pipeline runs on GitHub's servers on a schedule — your computer can be off.
Here's what's set up and why:

**1. Code lives in a private GitHub repo**, pushed with `git push`. `.gitignore`
keeps `.env`, `client_secret.json`, and `token.json` out of the repo — those are
secrets and should never be committed.

**2. Secrets are stored in GitHub → Settings → Secrets and variables → Actions**,
encrypted, one per value:
- `DRIVE_FOLDER_ID`
- `GROQ_API_KEY`
- `META_ACCESS_TOKEN`
- `IG_BUSINESS_ACCOUNT_ID`
- `GOOGLE_CLIENT_SECRET_JSON` — the full contents of your local `client_secret.json`
- `GOOGLE_TOKEN_JSON` — the full contents of your local `token.json`

**3. `.github/workflows/pipeline.yml`** is the automation itself. On each scheduled
run, it: checks out the repo → installs dependencies → rebuilds `client_secret.json`
and `token.json` from the two secrets above → runs the right script for that time
slot → commits the updated `processed_log.json`/`publish_queue.json` back to the
repo so the next run remembers what's already been done.

**4. Three schedules** (cron times are UTC, converted from IST):
- Slot A upload: `0 4 * * *` (9:30 AM IST)
- Slot B upload: `0 8 * * *` (1:30 PM IST)
- Publish check: `*/15 * * * *` (every 15 min, all day)

**5. Manual testing**: GitHub repo → Actions tab → "PoddyGo Pipeline" → "Run workflow"
button — triggers an on-demand run without waiting for the schedule.

### Two expiry dates to track

- **Google refresh token expires in 7 days** unless the OAuth app is moved out of
  "Testing" mode. Fix: Google Cloud Console → your project → **Google Auth Platform
  → Audience** → **Publish app**. Do this once, early — it removes the 7-day limit.
- **Meta access token expires in ~60 days** (mid-September 2026, if generated in
  July 2026). When it expires, Instagram posting silently fails. Fix: redo the
  `fb_exchange_token` exchange (see Meta setup section above) and update the
  `META_ACCESS_TOKEN` secret on GitHub with the new token.

## Notes

- YouTube free quota: ~6 uploads/day (10,000 units, ~1,600/upload) — 2/day is well within it.
- Instagram fetches the video from the Drive shareable link server-side — that link
  is created automatically by `upload_unlisted.py` (`anyone with link, viewer` permission).
- `publish_queue.json` tracks what's waiting to go live; `processed_log.json` tracks
  what's already been picked from Drive so nothing gets uploaded twice.
- If Instagram publish fails but YouTube succeeded, the script logs it and continues —
  check the console output and retry manually if needed.