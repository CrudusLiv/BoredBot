# Outlook (university email) integration — design

**Date:** 2026-07-13
**Status:** Approved by CrudusLiv, pending implementation plan

## Context

Vesper's integration layer (`.claude/scripts/integrations/`) currently wires up GitHub, Google Calendar, Gmail, and the local vault filesystem. `USER.md` has described an Outlook integration for the university email account since project inception, but it was never built — `registry.py` has no entry for it, and `msal>=1.28.0` has sat unused in `.claude/requirements.txt`.

Classes started June 2026 and are now underway (confirmed 2026-07-13). CrudusLiv's university address is `B2300682@helplive.edu.my` (domain `helplive.edu.my`).

Deadline tracking is already handled by the existing GCal → `DEADLINES.md` auto-import (`voice/heartbeat.py:_check_deadline_import`) and needs no changes — CrudusLiv adds deadlines to Google Calendar by hand, and the heartbeat already pulls them in. Out of scope for this spec.

Also out of scope, per explicit decision: the "assignment repos code review" feature described in `USER.md` / `CLAUDE.md`. CrudusLiv doesn't want it — a separate follow-up can clean up those references.

## Goal

Read-only access to the university Outlook/M365 mailbox via Microsoft Graph, exposed the same way Gmail is: a CLI subcommand (`py query.py outlook recent`), wired into `registry.py` status checks. **CLI-only this round** — no heartbeat wiring (no auto-drafts, no toast on new university email). That's an explicit fast-follow once the auth flow is confirmed working end-to-end, not part of this build.

## Non-goals

- Sending mail (Outlook stays read-only, same hard limit as Gmail)
- Calendar access (CrudusLiv's course deadlines live in Google Calendar, not Outlook — no Graph Calendars.Read scope needed)
- Heartbeat integration (drafts, priority-bump toasts on new university email) — deferred
- Assignment-repo code review wiring — explicitly dropped by CrudusLiv

## Design

### 1. Auth — `integrations/msal_auth.py`

Mirrors `integrations/google_auth.py`'s shape and responsibilities:

```python
def get_token(scopes: list[str] = ["Mail.Read"]) -> str | None:
    """Returns a Graph access token, running MSAL device-code flow on first use."""
```

- `msal.PublicClientApplication(client_id, authority=f"https://login.microsoftonline.com/{tenant_id or 'common'}")`. `.env` already has an empty `OUTLOOK_TENANT_ID` placeholder from an earlier pass — honor it if set (some university tenants restrict multi-tenant `common` sign-in), otherwise fall back to `common`, which supports both work/school and personal MS accounts.
- Env var names: `.env` already has empty `OUTLOOK_CLIENT_ID` / `OUTLOOK_TENANT_ID` placeholders (not `MS_CLIENT_ID` — corrected after checking `.env` directly). Use these existing names throughout.
- Token cache: `msal.SerializableTokenCache`, persisted to `.claude/data/msal_token_cache.bin` (gitignored — add to `.gitignore` alongside `google_token.json`'s existing entry if not already covered).
- Flow: load cache from disk if present → `app.get_accounts()` → if an account exists, try `acquire_token_silent(scopes, account=accounts[0])` → on `None`/failure, fall back to `app.initiate_device_flow(scopes)`, print the returned `message` (contains the verification URL + code) to stderr, then `app.acquire_token_by_device_flow(flow)`. Persist cache to disk after any acquisition (silent or device flow) if `cache.has_state_changed`.
- Returns `None` on missing `OUTLOOK_CLIENT_ID` env var (checked before constructing the app), or on any MSAL error — logged to stderr, never raised. Mirrors `google_auth.get_credentials()`'s "return None, let the caller report absence" contract.

### 2. Integration — `integrations/outlook_int.py`

Mirrors `integrations/gmail_int.py`'s public shape:

```python
def list_recent(days: int = 7, max_results: int = 30) -> list[dict]
def get_body(msg_id: str) -> str
def handle_query(argv: list[str]) -> int
```

- `list_recent`: GET `https://graph.microsoft.com/v1.0/me/messages?$top={max_results}&$orderby=receivedDateTime desc&$select=id,subject,from,receivedDateTime,bodyPreview` with `Authorization: Bearer {token}`. Filter to the `days` window client-side (Graph's `$filter` + `$orderby` combination on `receivedDateTime` requires an extra `ConsistencyLevel: eventual` header and ends up more fragile than just fetching the most recent N and trimming locally — same trade-off Gmail's `newer_than:{days}d` query avoids by doing it server-side, but Graph makes server-side filtering enough of a footgun that client-side trim is the pragmatic call here).
- Returned dict shape matches Gmail's for downstream consistency: `{id, subject, from, date, snippet}` (`snippet` ← Graph's `bodyPreview`).
- `get_body`: GET `https://graph.microsoft.com/v1.0/me/messages/{id}?$select=body`. Graph's `body.content` is HTML (`body.contentType == "html"`) in the overwhelming common case; treat any other content type as already-plain-text passthrough.
- Both functions return `[]` / `""` on missing token or any HTTP/request error — never raise, matching `gmail_int`'s failure contract.
- Uses `requests` (already installed transitively via `msal`; added explicitly to `requirements.txt` for clarity — see below).

### 3. Shared HTML→text helper — `integrations/_html_text.py`

Small mechanical extraction: `gmail_int.py`'s `_HtmlText` parser class and `_html_to_text()` function move here unchanged, re-exported from `gmail_int` for backward compatibility (`from ._html_text import html_to_text as _html_to_text` or equivalent), and imported fresh by `outlook_int.py`. No behavior change to Gmail; existing `test_gmail_int.py` tests keep passing unmodified.

### 4. Wiring

- `registry.py`: new entry —
  ```python
  Integration(
      name="outlook",
      description="Outlook/M365 university mail (read-only)",
      requires_env=["OUTLOOK_CLIENT_ID"],
      notes="MSAL device-code flow — first run prints a URL + code to approve in a browser.",
  )
  ```
- `query.py`: import `outlook_int`, add `"outlook": outlook_int.handle_query` to `DISPATCH`, add `py query.py outlook recent [--days 7] [--max 30]` to the module docstring.
- `.env`: `OUTLOOK_CLIENT_ID` and `OUTLOOK_TENANT_ID` placeholders already exist (both empty). Add a comment above them pointing at the Azure app registration steps:
  ```
  # Outlook / Microsoft Graph (university email) — Azure Portal app registration
  # portal.azure.com -> Azure Active Directory -> App registrations -> New registration
  # Supported account types: "Accounts in any organizational directory and personal Microsoft accounts"
  # Authentication -> Advanced settings -> Allow public client flows -> Yes
  # API permissions -> Microsoft Graph -> Delegated -> Mail.Read, offline_access
  # OUTLOOK_TENANT_ID is optional — leave blank to use the multi-tenant "common" endpoint
  OUTLOOK_CLIENT_ID=
  OUTLOOK_TENANT_ID=
  ```
- `.claude/requirements.txt`: add `requests>=2.31` under the Phase 4 integrations block, next to `msal>=1.28.0`.

### 5. Profile / memory updates (data only, no code)

- `USER.md`:
  - Platforms table, Outlook row: Auth stays "MSAL device-code flow", Notes changes from "Defer until classes start (June 2026)" to "Read-only mail via Microsoft Graph (`Mail.Read`)."
  - Account/integration IDs: `Outlook address: B2300682@helplive.edu.my`, `University email domain: helplive.edu.my`
  - Status line: drop "Pre-semester. Classes begin June 2026." framing since classes are underway.
- `MEMORY.md`: resolve the "University email domain" open question (move into Decisions with today's date, remove from Open questions).

### 6. Testing — `tests/test_outlook_int.py`

Mirrors `tests/test_gmail_int.py`'s structure: mock `requests.get` (or a `_service`-equivalent seam in `outlook_int.py`) so no real network call or device-code flow ever runs in tests. Cases to cover, matching Gmail's existing coverage:

- `list_recent` returns `[]` when token is unavailable
- `list_recent` returns `[]` on empty inbox
- `list_recent` returns parsed rows, trimmed to the `days` window
- `get_body` prefers/handles `body.contentType == "html"` (via the shared `_html_text` helper) and returns `""` on missing token or request error
- `handle_query` — both `--json` and human-readable output paths
- A `msal_auth.get_token` test confirming it returns `None` (not raising) when `MS_CLIENT_ID` is unset

## Open items for the implementation plan

- Exact `.gitignore` check for `msal_token_cache.bin` (likely already covered by an existing `*.bin` or `.claude/data/` blanket rule — verify, don't assume).
- CrudusLiv still needs to do the Azure app registration manually (steps documented in `.env` comment above) before the integration can go from `[--]` to `[OK]` in `py query.py status`. This isn't blocking the code — the integration ships regardless and simply reports "not ready" via `registry.py`'s existing `missing()` mechanism until `OUTLOOK_CLIENT_ID` is set.
