# Outlook (university email) integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a read-only Outlook/M365 integration (Microsoft Graph, MSAL device-code auth) so `py query.py outlook recent` works the same way `py query.py gmail recent` does, wired into `registry.py` status checks.

**Architecture:** Mirror the existing Gmail/Google-auth pair exactly: a standalone auth module (`msal_auth.py`) that returns a bearer token, and an integration module (`outlook_int.py`) that calls Microsoft Graph REST endpoints with `requests`. A small pre-existing HTML→text helper in `gmail_int.py` gets extracted to a shared module so both integrations use it.

**Tech Stack:** Python 3.14, `msal>=1.28.0` (already in requirements), `requests` (new explicit dependency), `pytest` + `unittest.mock` for tests.

## Global Constraints

- Outlook integration is read-only — no send, no delete, no calendar access (spec: Non-goals).
- No heartbeat wiring in this plan — CLI-only (spec: Goal).
- Env vars: `OUTLOOK_CLIENT_ID` (required), `OUTLOOK_TENANT_ID` (optional, falls back to `common`) — both already exist as empty placeholders in `.env`.
- Token cache path: `.claude/data/msal_token_cache.bin` — already covered by the blanket `.claude/data/` gitignore rule (verified, no `.gitignore` change needed).
- All new integration functions return `[]` / `""` / `None` on any failure (missing token, HTTP error) — never raise. Matches `gmail_int.py` / `google_auth.py`'s existing contract.
- Existing `test_gmail_int.py` tests must keep passing unmodified after the HTML-helper extraction.

---

### Task 1: Extract shared HTML→text helper from `gmail_int.py`

**Files:**
- Create: `.claude/scripts/integrations/_html_text.py`
- Modify: `.claude/scripts/integrations/gmail_int.py:63-106` (remove `_BLOCK_TAGS`, `_HtmlText`, `_html_to_text`, import from the new module instead)
- Test: `tests/test_gmail_int.py` (existing — must pass unmodified, no new test needed for this task since behavior doesn't change)

**Interfaces:**
- Produces: `_html_text.html_to_text(html: str) -> str` — used by both `gmail_int.py` and (in Task 3) `outlook_int.py`.

- [ ] **Step 1: Create the shared module with the extracted parser**

Create `.claude/scripts/integrations/_html_text.py`:

```python
"""Shared HTML -> plain-text conversion for mail-body rendering.

Block tags become newlines, <a href> URLs are kept inline as
`anchor text <url>` so digest parsers (e.g. job-alert scanning) can
find links."""
from __future__ import annotations

from html.parser import HTMLParser

_BLOCK_TAGS = {"p", "div", "br", "tr", "li", "td", "h1", "h2", "h3", "h4", "table"}


class _HtmlText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.out: list[str] = []
        self._skip = 0
        self._href = ""

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1
        if tag in _BLOCK_TAGS:
            self.out.append("\n")
        if tag == "a":
            self._href = dict(attrs).get("href") or ""

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self._skip:
            self._skip -= 1
        if tag == "a" and self._href:
            self.out.append(f" <{self._href}>")
            self._href = ""
        if tag in _BLOCK_TAGS:
            self.out.append("\n")

    def handle_data(self, data):
        if not self._skip:
            self.out.append(data)


def html_to_text(html: str) -> str:
    p = _HtmlText()
    try:
        p.feed(html)
        p.close()
    except Exception:
        return html
    lines = (ln.strip() for ln in "".join(p.out).splitlines())
    return "\n".join(ln for ln in lines if ln)
```

- [ ] **Step 2: Update `gmail_int.py` to import from the shared module**

In `.claude/scripts/integrations/gmail_int.py`:

1. Remove line 8 (`from html.parser import HTMLParser`) — no longer used in this file once `_HtmlText` moves out.
2. Remove lines 63-106 (the `_BLOCK_TAGS` constant, `_HtmlText` class, and `_html_to_text` function).
3. Replace the import block at the top (lines 11-12):

```python
sys.path.insert(0, str(Path(__file__).parent))
from google_auth import get_credentials  # noqa: E402
from _html_text import html_to_text as _html_to_text  # noqa: E402
```

Everything else in `gmail_int.py` (the `get_body` function calling `_html_to_text(h)`) stays unchanged — it already calls the function by this name.

- [ ] **Step 3: Run the existing Gmail test suite to confirm no regression**

Run: `py -m pytest tests/test_gmail_int.py -v`
Expected: All existing tests PASS (same count as before the extraction — this is a pure refactor, no behavior change).

- [ ] **Step 4: Commit**

```bash
git add .claude/scripts/integrations/_html_text.py .claude/scripts/integrations/gmail_int.py
git commit -m "refactor(integrations): extract HTML-to-text helper into shared module"
```

---

### Task 2: MSAL device-code auth module

**Files:**
- Create: `.claude/scripts/integrations/msal_auth.py`
- Test: `tests/test_msal_auth.py`

**Interfaces:**
- Consumes: `os.environ["OUTLOOK_CLIENT_ID"]`, `os.environ.get("OUTLOOK_TENANT_ID")`, the `msal` package, `integrations._env` (already-loaded `.env`, same pattern as `google_auth.py`).
- Produces: `msal_auth.get_token(scopes: list[str] | None = None) -> str | None` — used by `outlook_int.py` in Task 3.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_msal_auth.py`:

```python
"""Tests for msal_auth — MSAL calls are mocked, no real device-code flow or network."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".claude" / "scripts"))
sys.path.insert(0, str(ROOT / ".claude" / "scripts" / "integrations"))

import integrations._env  # noqa: F401


def test_get_token_returns_none_without_client_id(monkeypatch):
    import importlib
    import integrations.msal_auth as ma
    importlib.reload(ma)
    monkeypatch.delenv("OUTLOOK_CLIENT_ID", raising=False)
    assert ma.get_token() is None


def test_get_token_uses_common_authority_when_no_tenant(monkeypatch):
    import importlib
    import integrations.msal_auth as ma
    importlib.reload(ma)
    monkeypatch.setenv("OUTLOOK_CLIENT_ID", "fake-client-id")
    monkeypatch.delenv("OUTLOOK_TENANT_ID", raising=False)

    mock_app = MagicMock()
    mock_app.get_accounts.return_value = []
    mock_app.initiate_device_flow.return_value = {
        "message": "Go to https://microsoft.com/devicelogin and enter CODE123",
        "device_code": "dc1",
    }
    mock_app.acquire_token_by_device_flow.return_value = {"access_token": "tok123"}

    with patch.object(ma.msal, "PublicClientApplication", return_value=mock_app) as ctor:
        token = ma.get_token(scopes=["Mail.Read"])

    assert token == "tok123"
    called_authority = ctor.call_args.kwargs["authority"]
    assert called_authority == "https://login.microsoftonline.com/common"


def test_get_token_uses_tenant_authority_when_set(monkeypatch):
    import importlib
    import integrations.msal_auth as ma
    importlib.reload(ma)
    monkeypatch.setenv("OUTLOOK_CLIENT_ID", "fake-client-id")
    monkeypatch.setenv("OUTLOOK_TENANT_ID", "tenant-abc")

    mock_app = MagicMock()
    mock_app.get_accounts.return_value = []
    mock_app.initiate_device_flow.return_value = {"message": "...", "device_code": "dc1"}
    mock_app.acquire_token_by_device_flow.return_value = {"access_token": "tok456"}

    with patch.object(ma.msal, "PublicClientApplication", return_value=mock_app) as ctor:
        token = ma.get_token(scopes=["Mail.Read"])

    assert token == "tok456"
    assert ctor.call_args.kwargs["authority"] == "https://login.microsoftonline.com/tenant-abc"


def test_get_token_silent_path_used_when_account_cached(monkeypatch):
    import importlib
    import integrations.msal_auth as ma
    importlib.reload(ma)
    monkeypatch.setenv("OUTLOOK_CLIENT_ID", "fake-client-id")

    mock_app = MagicMock()
    mock_app.get_accounts.return_value = [{"username": "b2300682@helplive.edu.my"}]
    mock_app.acquire_token_silent.return_value = {"access_token": "silent-tok"}

    with patch.object(ma.msal, "PublicClientApplication", return_value=mock_app):
        token = ma.get_token(scopes=["Mail.Read"])

    assert token == "silent-tok"
    mock_app.initiate_device_flow.assert_not_called()


def test_get_token_returns_none_on_device_flow_failure(monkeypatch):
    import importlib
    import integrations.msal_auth as ma
    importlib.reload(ma)
    monkeypatch.setenv("OUTLOOK_CLIENT_ID", "fake-client-id")

    mock_app = MagicMock()
    mock_app.get_accounts.return_value = []
    mock_app.initiate_device_flow.return_value = {"error": "bad_request"}

    with patch.object(ma.msal, "PublicClientApplication", return_value=mock_app):
        token = ma.get_token(scopes=["Mail.Read"])

    assert token is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `py -m pytest tests/test_msal_auth.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'integrations.msal_auth'`

- [ ] **Step 3: Write the implementation**

Create `.claude/scripts/integrations/msal_auth.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `py -m pytest tests/test_msal_auth.py -v`
Expected: All 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add .claude/scripts/integrations/msal_auth.py tests/test_msal_auth.py
git commit -m "feat(integrations): add MSAL device-code auth module for Outlook"
```

---

### Task 3: Outlook integration module (`list_recent`, `get_body`, `handle_query`)

**Files:**
- Create: `.claude/scripts/integrations/outlook_int.py`
- Test: `tests/test_outlook_int.py`

**Interfaces:**
- Consumes: `msal_auth.get_token(scopes: list[str] | None = None) -> str | None` (Task 2), `_html_text.html_to_text(html: str) -> str` (Task 1).
- Produces: `outlook_int.list_recent(days: int = 7, max_results: int = 30) -> list[dict]`, `outlook_int.get_body(msg_id: str) -> str`, `outlook_int.handle_query(argv: list[str]) -> int` — used by `query.py` in Task 4.
- Row shape from `list_recent`: `{"id": str, "subject": str, "from": str, "date": str, "snippet": str}` — matches `gmail_int.list_recent`'s shape.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_outlook_int.py`:

```python
"""Smoke tests for outlook_int -- Microsoft Graph HTTP calls are mocked, no network."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".claude" / "scripts"))
sys.path.insert(0, str(ROOT / ".claude" / "scripts" / "integrations"))

import integrations._env  # noqa: F401


def _iso(days_ago: int) -> str:
    dt = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _make_messages_response(messages: list[dict]):
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {"value": messages}
    return resp


def test_list_recent_returns_empty_without_token():
    import importlib
    import integrations.outlook_int as oi
    importlib.reload(oi)
    with patch.object(oi, "_get_token", return_value=None):
        assert oi.list_recent() == []


def test_list_recent_parses_and_trims_to_days_window():
    import importlib
    import integrations.outlook_int as oi
    importlib.reload(oi)

    messages = [
        {
            "id": "m1",
            "subject": "Assignment due",
            "from": {"emailAddress": {"address": "prof@helplive.edu.my", "name": "Prof X"}},
            "receivedDateTime": _iso(2),
            "bodyPreview": "Please submit by Friday",
        },
        {
            "id": "m2",
            "subject": "Old newsletter",
            "from": {"emailAddress": {"address": "news@example.com", "name": "News"}},
            "receivedDateTime": _iso(30),
            "bodyPreview": "Old stuff",
        },
    ]
    resp = _make_messages_response(messages)
    with patch.object(oi, "_get_token", return_value="tok"), \
         patch.object(oi.requests, "get", return_value=resp):
        items = oi.list_recent(days=7, max_results=30)

    assert len(items) == 1
    assert items[0]["id"] == "m1"
    assert items[0]["subject"] == "Assignment due"
    assert items[0]["from"] == "Prof X <prof@helplive.edu.my>"
    assert items[0]["snippet"] == "Please submit by Friday"


def test_list_recent_empty_inbox():
    import importlib
    import integrations.outlook_int as oi
    importlib.reload(oi)
    resp = _make_messages_response([])
    with patch.object(oi, "_get_token", return_value="tok"), \
         patch.object(oi.requests, "get", return_value=resp):
        assert oi.list_recent() == []


def test_list_recent_returns_empty_on_request_error():
    import importlib
    import integrations.outlook_int as oi
    importlib.reload(oi)
    with patch.object(oi, "_get_token", return_value="tok"), \
         patch.object(oi.requests, "get", side_effect=oi.requests.RequestException("boom")):
        assert oi.list_recent() == []


def test_get_body_returns_empty_without_token():
    import importlib
    import integrations.outlook_int as oi
    importlib.reload(oi)
    with patch.object(oi, "_get_token", return_value=None):
        assert oi.get_body("m1") == ""


def test_get_body_converts_html_content():
    import importlib
    import integrations.outlook_int as oi
    importlib.reload(oi)
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {
        "body": {"contentType": "html", "content": "<div>Hello</div><div>World</div>"}
    }
    with patch.object(oi, "_get_token", return_value="tok"), \
         patch.object(oi.requests, "get", return_value=resp):
        text = oi.get_body("m1")
    assert "Hello" in text
    assert "World" in text


def test_get_body_passes_through_text_content():
    import importlib
    import integrations.outlook_int as oi
    importlib.reload(oi)
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {"body": {"contentType": "text", "content": "plain body"}}
    with patch.object(oi, "_get_token", return_value="tok"), \
         patch.object(oi.requests, "get", return_value=resp):
        assert oi.get_body("m1") == "plain body"


def test_get_body_returns_empty_on_request_error():
    import importlib
    import integrations.outlook_int as oi
    importlib.reload(oi)
    with patch.object(oi, "_get_token", return_value="tok"), \
         patch.object(oi.requests, "get", side_effect=oi.requests.RequestException("boom")):
        assert oi.get_body("m1") == ""


def test_handle_query_recent_json(capsys):
    import importlib
    import integrations.outlook_int as oi
    importlib.reload(oi)
    messages = [{
        "id": "m1",
        "subject": "Test Subject",
        "from": {"emailAddress": {"address": "sender@example.com", "name": "Sender"}},
        "receivedDateTime": _iso(1),
        "bodyPreview": "Hello there",
    }]
    resp = _make_messages_response(messages)
    with patch.object(oi, "_get_token", return_value="tok"), \
         patch.object(oi.requests, "get", return_value=resp):
        rc = oi.handle_query(["recent", "--days", "3", "--max", "5", "--json"])

    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert isinstance(data, list)
    assert data[0]["subject"] == "Test Subject"


def test_handle_query_recent_human(capsys):
    import importlib
    import integrations.outlook_int as oi
    importlib.reload(oi)
    messages = [{
        "id": "m1",
        "subject": "Test Subject",
        "from": {"emailAddress": {"address": "sender@example.com", "name": "Sender"}},
        "receivedDateTime": _iso(1),
        "bodyPreview": "Hello there",
    }]
    resp = _make_messages_response(messages)
    with patch.object(oi, "_get_token", return_value="tok"), \
         patch.object(oi.requests, "get", return_value=resp):
        rc = oi.handle_query(["recent"])

    assert rc == 0
    out = capsys.readouterr().out
    assert "Test Subject" in out
    assert "sender@example.com" in out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `py -m pytest tests/test_outlook_int.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'integrations.outlook_int'`

- [ ] **Step 3: Write the implementation**

Create `.claude/scripts/integrations/outlook_int.py`:

```python
"""Outlook/M365 integration -- read-only university mail via Microsoft Graph."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import requests  # noqa: E402
from msal_auth import get_token as _get_token  # noqa: E402
from _html_text import html_to_text  # noqa: E402

GRAPH_BASE = "https://graph.microsoft.com/v1.0"


def _format_from(from_field: dict) -> str:
    addr = (from_field or {}).get("emailAddress", {})
    name = addr.get("name", "")
    email = addr.get("address", "")
    if name and email:
        return f"{name} <{email}>"
    return email or name


def list_recent(days: int = 7, max_results: int = 30) -> list[dict]:
    token = _get_token()
    if not token:
        return []
    try:
        resp = requests.get(
            f"{GRAPH_BASE}/me/messages",
            headers={"Authorization": f"Bearer {token}"},
            params={
                "$top": max_results,
                "$orderby": "receivedDateTime desc",
                "$select": "id,subject,from,receivedDateTime,bodyPreview",
            },
            timeout=15,
        )
        resp.raise_for_status()
    except requests.RequestException as exc:
        print(f"outlook_int.list_recent: request failed: {exc}", file=sys.stderr)
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    out: list[dict] = []
    for msg in resp.json().get("value", []):
        received_raw = msg.get("receivedDateTime", "")
        try:
            received = datetime.strptime(received_raw, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        if received < cutoff:
            continue
        out.append({
            "id": msg["id"],
            "subject": msg.get("subject", ""),
            "from": _format_from(msg.get("from")),
            "date": received_raw,
            "snippet": msg.get("bodyPreview", ""),
        })
    return out


def get_body(msg_id: str) -> str:
    token = _get_token()
    if not token:
        return ""
    try:
        resp = requests.get(
            f"{GRAPH_BASE}/me/messages/{msg_id}",
            headers={"Authorization": f"Bearer {token}"},
            params={"$select": "body"},
            timeout=15,
        )
        resp.raise_for_status()
    except requests.RequestException as exc:
        print(f"outlook_int.get_body: request failed for {msg_id}: {exc}", file=sys.stderr)
        return ""

    body = resp.json().get("body", {})
    content = body.get("content", "")
    if not content:
        return ""
    if body.get("contentType") == "html":
        return html_to_text(content)
    return content


def handle_query(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="query.py outlook")
    sub = parser.add_subparsers(dest="subcommand", required=True)
    p = sub.add_parser("recent")
    p.add_argument("--days", type=int, default=7)
    p.add_argument("--max", type=int, default=30)
    p.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    rows = list_recent(args.days, args.max)
    if args.json:
        print(json.dumps(rows, indent=2, ensure_ascii=False, default=str))
    else:
        if not rows:
            print(f"(no messages in the last {args.days} days)")
        for r in rows:
            print(f"{r['date']}  {r['from']}  —  {r['subject']}")
            if r.get("snippet"):
                print(f"    {r['snippet'][:120]}")
    return 0


if __name__ == "__main__":
    sys.exit(handle_query(sys.argv[1:]))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `py -m pytest tests/test_outlook_int.py -v`
Expected: All 10 tests PASS

- [ ] **Step 5: Commit**

```bash
git add .claude/scripts/integrations/outlook_int.py tests/test_outlook_int.py
git commit -m "feat(integrations): add read-only Outlook integration via Microsoft Graph"
```

---

### Task 4: Wire into `registry.py` and `query.py`

**Files:**
- Modify: `.claude/scripts/integrations/registry.py:44-68` (add Integration entry to `INTEGRATIONS` list)
- Modify: `.claude/scripts/query.py:1-48` (docstring, import, DISPATCH)
- Test: `tests/test_query_dispatch.py` (new — thin smoke test; if a broader dispatch test file already covers `DISPATCH`, extend it instead of creating a new one — check first)

**Interfaces:**
- Consumes: `outlook_int.handle_query` (Task 3).
- Produces: `py query.py outlook recent` CLI command; `outlook` entry visible in `py query.py status`.

- [ ] **Step 1: Check whether a dispatch test file already exists**

Run: `py -m pytest --collect-only -q tests/ | grep -i dispatch`

If a file like `tests/test_query_dispatch.py` exists, read it and add the Outlook case to it instead of creating a new file. If none exists, proceed with Step 2 to create one (this is the first test for `query.py`'s dispatch table, matching the pattern where each integration's own test file covers its `handle_query`, but nothing currently checks the DISPATCH wiring itself).

- [ ] **Step 2: Write the failing test**

Create `tests/test_query_dispatch.py`:

```python
"""Smoke test for query.py's DISPATCH table -- confirms outlook is wired in."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".claude" / "scripts"))
sys.path.insert(0, str(ROOT / ".claude" / "scripts" / "integrations"))


def test_outlook_registered_in_dispatch():
    import importlib
    import query as q
    importlib.reload(q)
    assert "outlook" in q.DISPATCH


def test_outlook_registered_in_registry_status():
    import importlib
    import integrations.registry as registry
    importlib.reload(registry)
    names = [i.name for i in registry.INTEGRATIONS]
    assert "outlook" in names
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `py -m pytest tests/test_query_dispatch.py -v`
Expected: FAIL — `AssertionError` (outlook not yet in DISPATCH / INTEGRATIONS)

- [ ] **Step 4: Add the registry entry**

In `.claude/scripts/integrations/registry.py`, add to the `INTEGRATIONS` list (after the `vault` entry, line 63-67):

```python
    Integration(
        name="outlook",
        description="Outlook/M365 university mail (read-only)",
        requires_env=["OUTLOOK_CLIENT_ID"],
        notes="MSAL device-code flow -- first run prints a URL + code to approve in a browser.",
    ),
```

- [ ] **Step 5: Wire `query.py`**

In `.claude/scripts/query.py`:

Update the docstring (after line 13, `py query.py gmail recent...`):

```
    py query.py gmail recent [--days 7] [--max 30]

    py query.py outlook recent [--days 7] [--max 30]
```

Update the import block (lines 35-41):

```python
from integrations import (  # noqa: E402
    gcal_int,
    github_int,
    gmail_int,
    outlook_int,
    registry,
    vault_fs,
)
```

Update `DISPATCH` (lines 43-48):

```python
DISPATCH = {
    "github": github_int.handle_query,
    "gcal": gcal_int.handle_query,
    "gmail": gmail_int.handle_query,
    "outlook": outlook_int.handle_query,
    "vault": vault_fs.handle_query,
}
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `py -m pytest tests/test_query_dispatch.py -v`
Expected: Both tests PASS

- [ ] **Step 7: Run the full test suite for a regression check**

Run: `py -m pytest tests/test_gmail_int.py tests/test_msal_auth.py tests/test_outlook_int.py tests/test_query_dispatch.py -v`
Expected: All PASS

- [ ] **Step 8: Commit**

```bash
git add .claude/scripts/integrations/registry.py .claude/scripts/query.py tests/test_query_dispatch.py
git commit -m "feat(integrations): wire Outlook into registry status and query dispatch"
```

---

### Task 5: Config, requirements, and profile updates

**Files:**
- Modify: `.env` (add comment above existing `OUTLOOK_CLIENT_ID` / `OUTLOOK_TENANT_ID` placeholders)
- Modify: `.claude/requirements.txt:19` (add `requests>=2.31` after `msal>=1.28.0`)
- Modify: `Dynamous/Memory/USER.md` (lines 24, 78-79, 8)
- Modify: `Dynamous/Memory/MEMORY.md` (lines 30, 75)

No test for this task — it's config/profile data, not code. Verification is manual (Step 5).

- [ ] **Step 1: Update `.env`**

Find the existing `OUTLOOK_TENANT_ID=` / `OUTLOOK_CLIENT_ID=` lines (around lines 33-34) and add a comment block directly above them:

```
# Outlook / Microsoft Graph (university email) -- Azure Portal app registration
# portal.azure.com -> Azure Active Directory -> App registrations -> New registration
# Supported account types: "Accounts in any organizational directory and personal Microsoft accounts"
# Authentication -> Advanced settings -> Allow public client flows -> Yes
# API permissions -> Microsoft Graph -> Delegated -> Mail.Read, offline_access
# OUTLOOK_TENANT_ID is optional -- leave blank to use the multi-tenant "common" endpoint
OUTLOOK_TENANT_ID=
OUTLOOK_CLIENT_ID=
```

(Preserve whatever existing value, if any, is already on those lines -- these were confirmed empty during design, but re-check before overwriting.)

- [ ] **Step 2: Add `requests` to requirements**

In `.claude/requirements.txt`, after line 19 (`msal>=1.28.0`):

```
requests>=2.31
```

- [ ] **Step 3: Update `USER.md`**

In `Dynamous/Memory/USER.md`:

Line 8, change:
```
- **Status (as of 2026-05-08):** Pre-semester. Classes begin June 2026. Currently unemployed.
```
to:
```
- **Status (as of 2026-07-13):** Classes underway since June 2026. Currently unemployed.
```

Line 24, change:
```
| Outlook | University email | MSAL device-code flow | Defer until classes start (June 2026) |
```
to:
```
| Outlook | University email | MSAL device-code flow | Read-only mail via Microsoft Graph (`Mail.Read`) |
```

Lines 78-79, change:
```
- Gmail address: _(your Gmail address)_
- Outlook address: _(your university email)_
- University email domain: _(e.g., `students.university.edu.my`)_
```
to (keep the Gmail line as-is if it's already filled in elsewhere; only Outlook/domain are in scope here):
```
- Outlook address: B2300682@helplive.edu.my
- University email domain: helplive.edu.my
```

- [ ] **Step 4: Update `MEMORY.md`**

In `Dynamous/Memory/MEMORY.md`, add a new line under `## Decisions` (after line 30):

```
- 2026-07-13 — University email domain is `helplive.edu.my` (Outlook address `B2300682@helplive.edu.my`); Outlook integration built as CLI-only Microsoft Graph read access, heartbeat wiring deferred
```

Remove the resolved item from `## Open questions` (line 75):
```
- University email domain — needed for Gmail filter rules; fill in once classes start.
```

- [ ] **Step 5: Manual verification**

Run: `py .claude/scripts/query.py status`
Expected: `outlook` row appears in the output, marked `[--]` with `missing: env:OUTLOOK_CLIENT_ID` (since CrudusLiv hasn't done the Azure app registration yet -- this is expected and correct, not a bug).

- [ ] **Step 6: Commit**

```bash
git add .env .claude/requirements.txt Dynamous/Memory/USER.md Dynamous/Memory/MEMORY.md
git commit -m "chore(outlook): fill in university email profile data, add requests dependency"
```

---

## Post-plan manual step (not a task -- CrudusLiv does this, not the implementer)

Once all 5 tasks are merged, CrudusLiv registers the Azure AD app at portal.azure.com (steps in the `.env` comment from Task 5), sets `OUTLOOK_CLIENT_ID` (and optionally `OUTLOOK_TENANT_ID`) in `.env`, then runs `py .claude/scripts/query.py outlook recent` once to complete the device-code sign-in. This flips `outlook` to `[OK]` in `py query.py status`. Heartbeat wiring (auto-drafts, priority-bump toasts on new university email) is an explicit fast-follow, not part of this plan.
