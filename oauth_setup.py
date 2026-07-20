"""
One-time OAuth authorization. Run this once:

    python oauth_setup.py

It opens a browser, you log in with the Google account that owns the Drive
folder and the YouTube channel, and it saves a reusable token.json.
"""

import os

from google_auth_oauthlib.flow import InstalledAppFlow

from auth import SCOPES, TOKEN_FILE  # single source of truth for both

CLIENT_SECRET_FILE = "client_secret.json"


def main() -> None:
    if not os.path.exists(CLIENT_SECRET_FILE):
        raise FileNotFoundError(
            f"{CLIENT_SECRET_FILE} not found. Download it from Google Cloud Console "
            "(APIs & Services → Credentials → your OAuth Client ID → Download JSON) "
            "and place it in this folder."
        )

    flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET_FILE, SCOPES)
    creds = flow.run_local_server(port=0)

    with open(TOKEN_FILE, "w") as fh:
        fh.write(creds.to_json())

    print(
        f"Success. Saved credentials to {TOKEN_FILE}.\n"
        "You can now run `python upload_unlisted.py --slot A` (or B)."
    )


if __name__ == "__main__":
    main()
