"""Shared Microsoft Graph OAuth2 (MSAL device-code flow) -- used by Outlook.

First run prints a URL + one-time code to stderr for the user to approve
in a browser; subsequent runs use the cached refresh token at
.claude/data/msal_token_cache.bin.

Setup:
1. portal.azure.com -> Azure Active Directory -> App registrations -> New registration.
2. Supported account types: "Accounts in any organizational directory and
   personal Microsoft accounts".
3. Authentication -> Advanced settings -> Allow public client flows -> Yes.
4. API permissions -> Microsoft Graph -> Delegated -> Mail.Read, offline_access.
5. Add to .env:
       OUTLOOK_CLIENT_ID=<Application (client) ID from the Overview page>
       OUTLOOK_TENANT_ID=<optional -- leave blank to use the "common" endpoint>
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from integrations._env import load_env  # ensures .env is loaded  # noqa: F401

PROJECT_DIR = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[3])
TOKEN_CACHE_PATH = PROJECT_DIR / ".claude" / "data" / "msal_token_cache.bin"

DEFAULT_SCOPES = ["Mail.Read"]

try:
    import msal
except ImportError:
    msal = None  # type: ignore


def _authority() -> str:
    tenant = os.environ.get("OUTLOOK_TENANT_ID", "").strip()
    return f"https://login.microsoftonline.com/{tenant or 'common'}"


def _load_cache() -> "msal.SerializableTokenCache":
    cache = msal.SerializableTokenCache()
    if TOKEN_CACHE_PATH.exists():
        cache.deserialize(TOKEN_CACHE_PATH.read_text(encoding="utf-8"))
    return cache


def _save_cache(cache: "msal.SerializableTokenCache") -> None:
    if cache.has_state_changed:
        TOKEN_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        TOKEN_CACHE_PATH.write_text(cache.serialize(), encoding="utf-8")


def get_token(scopes: list[str] | None = None) -> str | None:
    """Returns a Microsoft Graph access token, running MSAL device-code
    flow on first use. Returns None on missing config or any MSAL error --
    never raises."""
    if msal is None:
        print("msal package missing: py -m pip install -r .claude/requirements.txt", file=sys.stderr)
        return None

    client_id = os.environ.get("OUTLOOK_CLIENT_ID", "")
    if not client_id:
        print("OUTLOOK_CLIENT_ID not set in .env.", file=sys.stderr)
        return None

    scopes = scopes or DEFAULT_SCOPES
    cache = _load_cache()
    app = msal.PublicClientApplication(client_id, authority=_authority(), token_cache=cache)

    result = None
    accounts = app.get_accounts()
    if accounts:
        result = app.acquire_token_silent(scopes, account=accounts[0])

    if not result:
        flow = app.initiate_device_flow(scopes)
        if "user_code" not in flow and "message" not in flow:
            print(f"msal_auth: device flow init failed: {flow.get('error_description', flow)}", file=sys.stderr)
            return None
        print(flow.get("message", "Approve the sign-in request in your browser."), file=sys.stderr)
        result = app.acquire_token_by_device_flow(flow)

    _save_cache(cache)

    if not result or "access_token" not in result:
        print(f"msal_auth: token acquisition failed: {result.get('error_description', result) if result else 'no result'}", file=sys.stderr)
        return None
    return result["access_token"]
