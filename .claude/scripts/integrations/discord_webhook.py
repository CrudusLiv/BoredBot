"""Low-level Discord webhook client.

One-way outbound to channel webhooks. urllib only (matches heartbeat.notify's
no-extra-deps stance) and Discord's required User-Agent format.

Used by heartbeat.dashboard for dashboard-channel posts. NOT for bot identity
sends -- those continue through heartbeat.notify (DMs to CrudusLiv only).

Returns parsed JSON from POST so callers can capture message_id and (for
forum-channel creates) the new thread id."""
from __future__ import annotations

import json
import urllib.request
from typing import Any

USER_AGENT = "DiscordBot (https://github.com/CrudusLiv/Vesper, 1.0)"
TIMEOUT = 10


def _safe_id(value: Any) -> str:
    """Convert a Discord snowflake to a clean digit string.

    Handles int, str, and float-as-str (e.g. '1.23e18' from SQLite REAL columns).
    Returns the integer portion; raises ValueError for non-numeric inputs."""
    s = str(value).split(".")[0]
    return str(int(s))


def post(
    url: str,
    *,
    content: str | None = None,
    embeds: list[dict] | None = None,
    thread_name: str | None = None,
    thread_id: str | None = None,
    applied_tags: list[str] | None = None,
) -> dict[str, Any]:
    """POST a message via webhook. `?wait=true` is always set so the response
    includes the new message id (and, for forum-channel creates with
    thread_name, the thread/post id as `channel_id`)."""
    body: dict[str, Any] = {}
    if content is not None:
        body["content"] = content
    if embeds:
        body["embeds"] = embeds
    if thread_name:
        body["thread_name"] = thread_name
    if applied_tags:
        body["applied_tags"] = applied_tags

    query = "?wait=true"
    if thread_id:
        try:
            tid = int(_safe_id(thread_id))
            if tid > 0:
                query += f"&thread_id={tid}"
        except (ValueError, TypeError):
            pass
    return _request(f"{url}{query}", method="POST", body=body)


def edit(
    url: str,
    message_id: str,
    *,
    content: str | None = None,
    embeds: list[dict] | None = None,
    thread_id: str | None = None,
) -> dict[str, Any]:
    """PATCH an existing webhook message. Only works on messages this webhook
    posted. Pass thread_id when the message lives inside a thread."""
    body: dict[str, Any] = {}
    if content is not None:
        body["content"] = content
    if embeds is not None:
        body["embeds"] = embeds
    path = f"{url}/messages/{message_id}"
    query = f"?thread_id={_safe_id(thread_id)}" if thread_id else ""
    return _request(f"{path}{query}", method="PATCH", body=body)


def delete(url: str, message_id: str, *, thread_id: str | None = None) -> None:
    path = f"{url}/messages/{message_id}"
    query = f"?thread_id={_safe_id(thread_id)}" if thread_id else ""
    _request(f"{path}{query}", method="DELETE", body=None, expect_json=False)


def _request(url: str, *, method: str, body: dict | None, expect_json: bool = True) -> dict[str, Any]:
    import urllib.error
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url,
        method=method,
        data=data,
        headers={
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise urllib.error.HTTPError(
            exc.url, exc.code, f"{exc.msg} — {detail}", exc.headers, None
        ) from None
    if not expect_json or not raw:
        return {}
    return json.loads(raw)
