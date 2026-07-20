"""
Shared Google OAuth credentials helper.

Centralises SCOPES and get_credentials() so upload_unlisted.py,
publish_scheduled.py, and oauth_setup.py all use the same definitions
and token-refresh logic.
"""

import os
from google.oauth2.credentials import Credentials

TOKEN_FILE = os.environ.get("TOKEN_FILE", "token.json")

# All Google API scopes needed by the pipeline.
# Change here propagates everywhere automatically.
SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
]


def get_credentials() -> Credentials:
    """
    Load credentials from TOKEN_FILE, refreshing them if expired.

    Raises:
        FileNotFoundError: if token.json is missing (run oauth_setup.py first).
        google.auth.exceptions.RefreshError: if the refresh token is invalid
            or the OAuth app is still in Testing mode (7-day expiry).
    """
    if not os.path.exists(TOKEN_FILE):
        raise FileNotFoundError(
            f"{TOKEN_FILE} not found. Run `python oauth_setup.py` first to "
            "authenticate with Google."
        )

    creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

    if creds.expired and creds.refresh_token:
        from google.auth.transport.requests import Request  # lazy import

        creds.refresh(Request())
        with open(TOKEN_FILE, "w") as fh:
            fh.write(creds.to_json())

    return creds
