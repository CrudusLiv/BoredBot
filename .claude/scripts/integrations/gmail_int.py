"""Gmail integration -- read-only. Shares OAuth token with Google Calendar."""
from __future__ import annotations

import argparse
import base64
import json
import sys
from html.parser import HTMLParser
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


_BLOCK_TAGS = {"p", "div", "br", "tr", "li", "td", "h1", "h2", "h3", "h4", "table"}


class _HtmlText(HTMLParser):
    """Minimal HTML → text: block tags become newlines, <a href> URLs are
    kept inline as `anchor text <url>` so digest parsers can find job links."""

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


def _html_to_text(html: str) -> str:
    p = _HtmlText()
    try:
        p.feed(html)
        p.close()
    except Exception:
        return html
    lines = (ln.strip() for ln in "".join(p.out).splitlines())
    return "\n".join(ln for ln in lines if ln)


def _walk_parts(payload: dict):
    yield payload
    for part in payload.get("parts") or []:
        yield from _walk_parts(part)


def _decode_part(part: dict) -> str:
    data = (part.get("body") or {}).get("data", "")
    if not data:
        return ""
    try:
        return base64.urlsafe_b64decode(data + "===").decode("utf-8", "replace")
    except Exception:
        return ""


def get_body(msg_id: str) -> str:
    """Fetch a message's full body as readable text. text/plain parts are
    preferred; text/html parts are converted with hrefs preserved inline.
    Returns "" on any failure."""
    svc = _service()
    if not svc:
        return ""
    try:
        msg = svc.users().messages().get(
            userId="me", id=msg_id, format="full",
        ).execute()
    except Exception as exc:
        print(f"gmail_int.get_body: get failed for {msg_id}: {exc}", file=sys.stderr)
        return ""
    plain: list[str] = []
    html: list[str] = []
    for part in _walk_parts(msg.get("payload") or {}):
        mime = part.get("mimeType", "")
        text = _decode_part(part)
        if not text:
            continue
        if mime == "text/plain":
            plain.append(text)
        elif mime == "text/html":
            html.append(text)
    if plain:
        return "\n".join(plain)
    if html:
        return "\n".join(_html_to_text(h) for h in html)
    return ""


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
