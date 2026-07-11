"""Job-alert tracker: JSON store of postings extracted from job-alert digest
emails, plus the application drafter. Store/parser functions are pure; only
scan_alerts() (Gmail) and draft_application() (LLM + vault) touch the world.

Scanning is silent by design — nothing here posts a heartbeat notice; the
Jobs panel in the orb UI is where postings are browsed. The drafter never
sends anything: it writes to drafts/active/ via write_draft() and stops."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

JOBS_FILE = "jobs.json"
STATUSES = {"new", "drafted", "applied", "dismissed"}


def job_id(link: str) -> str:
    return hashlib.sha1(link.encode("utf-8")).hexdigest()[:12]


def load_jobs(data_dir: Path) -> list[dict]:
    p = Path(data_dir) / JOBS_FILE
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def _save_jobs(data_dir: Path, rows: list[dict]) -> None:
    p = Path(data_dir) / JOBS_FILE
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    tmp.replace(p)


def add_postings(data_dir: Path, postings: list[dict],
                 now: str | None = None) -> int:
    """Insert new postings, deduped by link hash — a dismissed record keeps
    its id in the store, so it never resurfaces. Returns the number added."""
    rows = load_jobs(data_dir)
    known = {r["id"] for r in rows}
    now = now or datetime.now(timezone.utc).isoformat()
    added = 0
    for post in postings:
        link = (post.get("link") or "").strip()
        if not link:
            continue                      # link is the dedup key
        jid = job_id(link)
        if jid in known:
            continue
        rows.append({
            "id": jid,
            "title": post.get("title", ""),
            "company": post.get("company", ""),
            "location": post.get("location", ""),
            "remote": post.get("remote", ""),
            "link": link,
            "source": post.get("source", ""),
            "status": "new",
            "first_seen": now,
        })
        known.add(jid)
        added += 1
    if added:
        _save_jobs(data_dir, rows)
    return added


def update_status(data_dir: Path, jid: str, status: str) -> bool:
    if status not in STATUSES:
        return False
    rows = load_jobs(data_dir)
    for r in rows:
        if r["id"] == jid:
            r["status"] = status
            _save_jobs(data_dir, rows)
            return True
    return False


def get_job(data_dir: Path, jid: str) -> dict | None:
    for r in load_jobs(data_dir):
        if r["id"] == jid:
            return r
    return None
