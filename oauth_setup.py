"""
One-time OAuth authorization. Run this once:

    python oauth_setup.py

It opens a browser, you log in with the Google account that owns the Drive
folder and the YouTube channel, and it saves a reusable token.json.
"""

from google_auth_oauthlib.flow import InstalledAppFlow
import json
import os

SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
]

CLIENT_SECRET_FILE = "client_secret.json"
TOKEN_FILE = "token.json"


def main():
    if not os.path.exists(CLIENT_SECRET_FILE):
        raise FileNotFoundError(
            f"{CLIENT_SECRET_FILE} not found. Download it from Google Cloud Console "
            f"(APIs & Services -> Credentials -> your OAuth Client ID -> Download JSON) "
            f"and place it in this folder."
        )

    flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET_FILE, SCOPES)
    creds = flow.run_local_server(port=0)

    with open(TOKEN_FILE, "w") as f:
        f.write(creds.to_json())

    print(f"Success. Saved credentials to {TOKEN_FILE}. You can now run pipeline.py")


if __name__ == "__main__":
    main()
