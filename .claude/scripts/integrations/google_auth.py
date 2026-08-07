"""Shared Google OAuth2 -- used by Gmail and Calendar.

First run opens a browser for consent; subsequent runs use the cached
refresh token at .claude/data/google_token.json.

Setup:
1. Google Cloud Console -> enable Gmail API + Calendar API.
2. Credentials -> OAuth client ID -> Desktop app -> download JSON.
3. Add to .env:
       GOOGLE_CLIENT_ID=<client_id from the JSON>
       GOOGLE_CLIENT_SECRET=<client_secret from the JSON>

Both Gmail and Calendar scopes are requested up front so the user only
consents once. Read-only -- no compose, no event create/delete."""
from __future__ import annotations

import os
import sys
from pathlib import Path

from integrations._env import load_env  # ensures .env is loaded  # noqa: F401

PROJECT_DIR = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[3])
TOKEN_PATH = PROJECT_DIR / ".claude" / "data" / "google_token.json"

SCOPES = [
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/gmail.readonly",
]


def get_credentials():
    """Returns google.oauth2.credentials.Credentials, running OAuth on first use."""
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        print("Google libs missing: py -m pip install -r .claude/requirements.txt", file=sys.stderr)
        return None

    client_id = os.environ.get("GOOGLE_CLIENT_ID", "")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        print(
            "GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET not set in .env.\n"
            "Get them from Google Cloud Console -> Credentials -> OAuth Desktop client.",
            file=sys.stderr,
        )
        return None

    client_config = {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uris": ["http://localhost"],
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }

    creds = None
    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
            creds = flow.run_local_server(port=0)
        TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
        TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
    return creds
