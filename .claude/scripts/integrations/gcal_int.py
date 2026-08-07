"""Google Calendar integration -- read-only. Shares OAuth token with Gmail."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
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
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


def upcoming(days: int = 14, max_results: int = 50) -> list[dict]:
    svc = _service()
    if not svc:
        return []
    now = datetime.now(timezone.utc)
    later = now + timedelta(days=days)
    try:
        resp = svc.events().list(
            calendarId="primary",
            timeMin=now.isoformat(),
            timeMax=later.isoformat(),
            maxResults=max_results,
            singleEvents=True,
            orderBy="startTime",
        ).execute()
    except Exception as exc:
        print(f"gcal_int.upcoming: API call failed: {exc}", file=sys.stderr)
        return []
    out: list[dict] = []
    for e in resp.get("items", []):
        start = e.get("start", {}).get("dateTime") or e.get("start", {}).get("date")
        end = e.get("end", {}).get("dateTime") or e.get("end", {}).get("date")
        out.append({
            "id": e.get("id"),
            "summary": e.get("summary", ""),
            "start": start,
            "end": end,
            "location": e.get("location", ""),
            "description": (e.get("description") or "")[:500],
        })
    return out


def handle_query(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="query.py gcal")
    parser.add_argument("--json", action="store_true")
    sub = parser.add_subparsers(dest="subcommand", required=True)
    p = sub.add_parser("upcoming")
    p.add_argument("--days", type=int, default=14)
    p.add_argument("--max", type=int, default=50)
    args = parser.parse_args(argv)
    json_out = args.json

    rows = upcoming(args.days, args.max)
    if json_out:
        print(json.dumps(rows, indent=2, ensure_ascii=False, default=str))
    else:
        if not rows:
            print(f"(no events in the next {args.days} days)")
        for r in rows:
            print(f"{r['start']}  {r['summary']}")
            if r.get("location"):
                print(f"    @ {r['location']}")
    return 0


if __name__ == "__main__":
    sys.exit(handle_query(sys.argv[1:]))
