"""Gmail integration -- read-only. Shares OAuth token with Google Calendar."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from google_auth import get_credentials  # noqa: E402


def _service():
    creds = get_credentials()
    if not creds:
        return None
    try:
        from googleapiclient.discovery import build
    except ImportError:
        print("google-api-python-client missing", file=sys.stderr)
        return None
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def list_recent(days: int = 7, max_results: int = 30) -> list[dict]:
    svc = _service()
    if not svc:
        return []
    try:
        resp = svc.users().messages().list(
            userId="me",
            q=f"newer_than:{days}d",
            maxResults=max_results,
        ).execute()
    except Exception as exc:
        print(f"gmail_int.list_recent: list call failed: {exc}", file=sys.stderr)
        return []
    out: list[dict] = []
    for stub in resp.get("messages", []):
        try:
            msg = svc.users().messages().get(
                userId="me",
                id=stub["id"],
                format="metadata",
                metadataHeaders=["Subject", "From", "Date"],
            ).execute()
        except Exception as exc:
            print(f"gmail_int.list_recent: get failed for {stub['id']}: {exc}", file=sys.stderr)
            continue
        headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
        out.append({
            "id": msg["id"],
            "subject": headers.get("Subject", ""),
            "from": headers.get("From", ""),
            "date": headers.get("Date", ""),
            "snippet": msg.get("snippet", ""),
        })
    return out


def handle_query(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="query.py gmail")
    sub = parser.add_subparsers(dest="subcommand", required=True)
    p = sub.add_parser("recent")
    p.add_argument("--days", type=int, default=7)
    p.add_argument("--max", type=int, default=30)
    p.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    json_out = args.json

    rows = list_recent(args.days, args.max)
    if json_out:
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
