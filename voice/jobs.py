"""Job-alert tracker: JSON store of postings extracted from job-alert digest
emails, plus the application drafter. Store/parser functions are pure; only
scan_alerts() (Gmail) and draft_application() (LLM + vault) touch the world.

Scanning is silent by design — nothing here posts a heartbeat notice; the
Jobs panel in the orb UI is where postings are browsed. The drafter never
sends anything: it writes to drafts/active/ via write_draft() and stops."""
from __future__ import annotations

import hashlib
import json
import re
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


# ---- digest parsing (heuristic, deterministic — never the LLM) ---------------

_URL_RE = re.compile(r"https?://[^\s<>\"']+")

_JOB_LINK_RES = {
    "linkedin.com": re.compile(
        r"https?://(?:[\w.-]+\.)?linkedin\.com/(?:comm/)?jobs/view/[^\s<>\"']+"),
    "indeed.com": re.compile(
        r"https?://(?:[\w.-]+\.)?indeed\.com/(?:rc/clk|viewjob|pagead/clk)[^\s<>\"']*"),
    "glassdoor.com": re.compile(
        r"https?://(?:[\w.-]+\.)?glassdoor\.com/(?:job-listing|partner)[^\s<>\"']*"),
}

_REMOTE_RE = re.compile(r"\b(remote|hybrid|on-?site)\b", re.IGNORECASE)


def match_sender(from_field: str, senders: list[str]) -> str | None:
    """Map an email From: header to a configured sender domain (which is also
    the parser key), matching the domain or any subdomain of it."""
    m = re.search(r"@([\w.-]+)", from_field or "")
    if not m:
        return None
    domain = m.group(1).lower().rstrip(">")
    for s in senders:
        base = s.lower().strip().lstrip("@")
        if domain == base or domain.endswith("." + base):
            return base
    return None


def _norm_remote(value: str) -> str:
    v = value.lower().replace("-", "")
    return "onsite" if v == "onsite" else v


def _context_fields(lines: list[str], idx: int) -> tuple[str, str, str, str]:
    """Read title/company/location/remote from up to 3 non-empty, non-URL
    lines preceding the link line. See the parsing contract in the plan."""
    ctx: list[str] = []                   # closest-first
    j = idx - 1
    while j >= 0 and len(ctx) < 3:
        ln = lines[j]
        if ln and not _URL_RE.search(ln):
            ctx.append(ln)
        j -= 1
    title = company = location = remote = ""
    meta_i = next((k for k, ln in enumerate(ctx) if "·" in ln), None)
    if meta_i is not None:
        # only the meta line + the title line above it belong to THIS posting;
        # anything farther back is the previous digest entry bleeding in
        used = ctx[:meta_i + 2]
        company, _, location = (part.strip() for part in ctx[meta_i].partition("·"))
        location = re.sub(r"\s*\((?:remote|hybrid|on-?site)\)\s*$", "",
                          location, flags=re.IGNORECASE).strip()
        if meta_i + 1 < len(ctx):
            title = ctx[meta_i + 1]
    else:
        used = ctx
        if len(ctx) == 3:
            location, company, title = ctx
        elif len(ctx) == 2:
            company, title = ctx
        elif len(ctx) == 1:
            title = ctx[0]
    for ln in used:
        m = _REMOTE_RE.search(ln)
        if m:
            remote = _norm_remote(m.group(1))
            break
    return title, company, location, remote


def _strip_tracking(source: str, link: str) -> str:
    # LinkedIn job-view URLs are stable without their query; Indeed/Glassdoor
    # carry the job key in the query, so theirs must be kept.
    if source == "linkedin.com":
        return link.split("?", 1)[0]
    return link


def parse_digest(source: str, text: str) -> list[dict]:
    """Extract postings from one digest email body. Unparseable postings are
    skipped, never raised — parser trouble must not abort the batch."""
    link_re = _JOB_LINK_RES.get(source)
    if not link_re:
        return []
    lines = [ln.strip() for ln in text.splitlines()]
    out: list[dict] = []
    seen_links: set[str] = set()
    for i, line in enumerate(lines):
        m = link_re.search(line)
        if not m:
            continue
        link = _strip_tracking(source, m.group(0).rstrip(">.,)"))
        if link in seen_links:
            continue
        seen_links.add(link)
        title, company, location, remote = _context_fields(lines, i)
        if not title:
            continue                      # not enough context to be useful
        out.append({"title": title, "company": company, "location": location,
                    "remote": remote, "link": link, "source": source})
    return out


# ---- scan pass (the only Gmail-touching function) -----------------------------

def scan_alerts(data_dir: Path, conf: dict) -> int:
    """One silent scan: list recent messages, keep those from configured
    job-alert senders, parse each body, insert new postings. One email's
    failure never aborts the batch. Returns the number of postings added."""
    import voice  # noqa: F401 — sys.path setup for .claude/scripts
    from integrations import gmail_int  # type: ignore
    senders = conf.get("job_alert_senders", [])
    days = int(conf.get("job_alert_lookback_days", 3))
    added = 0
    for msg in gmail_int.list_recent(days=days, max_results=50):
        source = match_sender(msg.get("from", ""), senders)
        if not source:
            continue
        try:
            body = gmail_int.get_body(msg["id"])
            added += add_postings(data_dir, parse_digest(source, body))
        except Exception as exc:
            print(f"[jobs] digest parse failed for {msg.get('id')}: {exc}", flush=True)
            continue
    return added


# ---- application drafter (manual trigger only — POST /cmd/jobs/draft) ---------

_DRAFT_SYSTEM = (
    "You write tailored job-application emails. Use only facts from the "
    "candidate's resume note — never invent experience, employers, dates, or "
    "qualifications. Output only the email: a Subject: line, a greeting, 2-3 "
    "short paragraphs matching the resume to the posting, and a sign-off. "
    "No commentary, no placeholders."
)


def _slug(text: str) -> str:
    import re as _re
    s = _re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return s or "job"


def draft_application(jid: str) -> dict:
    """Draft a tailored application email for one stored posting into
    drafts/active/ for manual review. Never sends anything; the only
    side effects are the draft file and the status flip to 'drafted'."""
    from voice import config as cfg
    from voice import llm
    import voice.tools.workspace as workspace

    data_dir = cfg.get_data_dir()
    job = get_job(data_dir, jid)
    if job is None:
        return {"ok": False, "error": "unknown job id"}
    vault = cfg.get_vault_dir()
    if vault is None:
        return {"ok": False, "error": "no vault configured"}
    try:
        resume = (vault / "profile" / "RESUME.md").read_text(encoding="utf-8").strip()
    except (OSError, ValueError):
        resume = ""
    if not resume:
        return {"ok": False, "error":
                "profile/RESUME.md is missing or empty — fill it in before drafting"}
    prompt = (
        "Job posting:\n"
        f"  Title: {job['title']}\n"
        f"  Company: {job['company']}\n"
        f"  Location: {job['location']}\n"
        f"  Remote: {job['remote'] or 'unstated'}\n"
        f"  Link: {job['link']}\n\n"
        f"Candidate resume note:\n{resume}\n\n"
        "Write the application email for this posting."
    )
    text = llm.call(prompt, system_prompt=_DRAFT_SYSTEM)
    if not text:
        return {"ok": False, "error": "LLM backend returned no draft"}
    name = f"{_slug(job['company'])}-{_slug(job['title'])}.md"
    result = workspace.write_draft(name, text)
    if not result.startswith("Wrote"):
        return {"ok": False, "error": result}
    update_status(data_dir, jid, "drafted")
    return {"ok": True, "name": name, "message": result}
