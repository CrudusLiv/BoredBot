"""Shared Google OAuth2 -- used by Gmail, Calendar, and Tasks (reminders).

First run opens a browser for consent; subsequent runs use the cached
refresh token at .claude/data/google_token.json. If SCOPES grows (e.g. this
module adding the Tasks scope), a cached token that predates the new scope
is detected and a fresh consent flow runs automatically instead of failing
later with an opaque 403 from the API.

Setup:
1. Google Cloud Console -> enable Gmail API + Calendar API + Tasks API.
2. Credentials -> OAuth client ID -> Desktop app -> download JSON.
3. Add to .env:
       GOOGLE_CLIENT_ID=<client_id from the JSON>
       GOOGLE_CLIENT_SECRET=<client_secret from the JSON>

Calendar and Tasks scopes include write access: gcal_write.py can create
and delete events, gtasks_write.py can create reminders. Gmail stays
read-only.

Multiple Google accounts: pass account=<label> to get_credentials() to use
a second (or third...) inbox -- e.g. a dedicated job-search Gmail separate
from the primary account. Each label gets its own cached token file
(.claude/data/google_token_<label>.json), so the primary account's
Calendar/Tasks/Gmail access is untouched. First call for a new label opens
its own browser consent -- sign into that account there."""
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
    "https://www.googleapis.com/auth/tasks",
]


def _token_path(account: str | None) -> Path:
    if not account:
        return TOKEN_PATH
    return TOKEN_PATH.with_name(f"google_token_{account}.json")


def get_credentials(account: str | None = None):
    """Returns google.oauth2.credentials.Credentials, running OAuth on first use.
    account=None uses the primary token; any other label gets its own
    cached token file and its own consent flow (see module docstring)."""
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

    token_path = _token_path(account)
    creds = None
    if token_path.exists():
        # Deliberately NOT passing scopes=SCOPES here: Credentials.
        # from_authorized_user_info only reads the file's own "scopes" field
        # when the scopes argument is None -- pass SCOPES explicitly and it
        # echoes SCOPES back as creds.scopes regardless of what was actually
        # granted, making the mismatch check below always pass trivially.
        creds = Credentials.from_authorized_user_file(str(token_path))
        if creds and not set(SCOPES).issubset(set(creds.scopes or [])):
            creds = None  # cached token predates a scope we now need — re-auth
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
            creds = flow.run_local_server(port=0)
        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text(creds.to_json(), encoding="utf-8")
    return creds
