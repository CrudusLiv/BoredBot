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

        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        out: list[dict] = []
        for msg in resp.json().get("value", []):
            received_raw = msg.get("receivedDateTime", "")
            try:
                received = datetime.fromisoformat(received_raw.replace("Z", "+00:00"))
            except ValueError:
                continue
            if received < cutoff:
                continue
            out.append({
                "id": msg.get("id", ""),
                "subject": msg.get("subject", ""),
                "from": _format_from(msg.get("from")),
                "date": received_raw,
                "snippet": msg.get("bodyPreview", ""),
            })
        return out
    except Exception as exc:
        print(f"outlook_int.list_recent: request failed: {exc}", file=sys.stderr)
        return []


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

        body = resp.json().get("body", {})
        content = body.get("content", "")
        if not content:
            return ""
        if body.get("contentType") == "html":
            return html_to_text(content)
        return content
    except Exception as exc:
        print(f"outlook_int.get_body: request failed for {msg_id}: {exc}", file=sys.stderr)
        return ""


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
