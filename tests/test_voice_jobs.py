"""Job-alert tracker tests: store CRUD/dedup, digest parsers, scan pass,
and the application drafter. No network, no real LLM calls."""
from pathlib import Path

import pytest

from voice import jobs


# ---- store ------------------------------------------------------------------

P1 = {"title": "Software Engineer", "company": "Acme", "location": "Kuala Lumpur",
      "remote": "remote", "link": "https://x.com/j/1", "source": "linkedin.com"}
P2 = {"title": "Backend Dev", "company": "Beta", "location": "Penang",
      "remote": "", "link": "https://x.com/j/2", "source": "indeed.com"}


def test_load_jobs_missing_returns_empty(tmp_path):
    assert jobs.load_jobs(tmp_path) == []


def test_load_jobs_corrupt_returns_empty(tmp_path):
    (tmp_path / jobs.JOBS_FILE).write_text("{not json", encoding="utf-8")
    assert jobs.load_jobs(tmp_path) == []


def test_load_jobs_invalid_utf8_returns_empty(tmp_path):
    (tmp_path / jobs.JOBS_FILE).write_bytes(b"\xff\xfe\x00garbage")
    assert jobs.load_jobs(tmp_path) == []


def test_add_postings_roundtrip(tmp_path):
    added = jobs.add_postings(tmp_path, [P1, P2], now="2026-07-11T12:00:00+08:00")
    assert added == 2
    rows = jobs.load_jobs(tmp_path)
    assert len(rows) == 2
    r = rows[0]
    assert r["title"] == "Software Engineer"
    assert r["company"] == "Acme"
    assert r["status"] == "new"
    assert r["first_seen"] == "2026-07-11T12:00:00+08:00"
    assert r["id"] == jobs.job_id(P1["link"])


def test_add_postings_dedups_by_link(tmp_path):
    assert jobs.add_postings(tmp_path, [P1]) == 1
    assert jobs.add_postings(tmp_path, [P1, P2]) == 1   # P1 already known
    assert len(jobs.load_jobs(tmp_path)) == 2


def test_add_postings_skips_missing_link(tmp_path):
    assert jobs.add_postings(tmp_path, [{"title": "No Link", "link": ""}]) == 0
    assert jobs.load_jobs(tmp_path) == []


def test_dedup_survives_dismissed_status(tmp_path):
    jobs.add_postings(tmp_path, [P1])
    jid = jobs.job_id(P1["link"])
    assert jobs.update_status(tmp_path, jid, "dismissed") is True
    assert jobs.add_postings(tmp_path, [P1]) == 0        # never resurfaces
    assert jobs.load_jobs(tmp_path)[0]["status"] == "dismissed"


def test_update_status_rejects_invalid(tmp_path):
    jobs.add_postings(tmp_path, [P1])
    jid = jobs.job_id(P1["link"])
    assert jobs.update_status(tmp_path, jid, "hired") is False
    assert jobs.load_jobs(tmp_path)[0]["status"] == "new"


def test_update_status_unknown_id(tmp_path):
    assert jobs.update_status(tmp_path, "nope", "applied") is False


def test_get_job(tmp_path):
    jobs.add_postings(tmp_path, [P1])
    jid = jobs.job_id(P1["link"])
    assert jobs.get_job(tmp_path, jid)["company"] == "Acme"
    assert jobs.get_job(tmp_path, "nope") is None


# ---- parsers ----------------------------------------------------------------

LINKEDIN_BODY = """\
Your job alert for software engineer

Software Engineer
Acme Sdn Bhd · Kuala Lumpur, Malaysia (Remote)
View job <https://www.linkedin.com/comm/jobs/view/4012345678?trk=abc>

Junior Backend Developer
Beta Tech · Petaling Jaya, Selangor
View job <https://www.linkedin.com/comm/jobs/view/4098765432?trk=def>

Unsubscribe <https://www.linkedin.com/e/unsub>
"""

INDEED_BODY = """\
New jobs for: developer

Full Stack Developer
Gamma Solutions
Kuala Lumpur
<https://my.indeed.com/rc/clk?jk=abc123&from=ja>

DevOps Engineer (Hybrid)
Delta Corp
Cyberjaya
<https://my.indeed.com/rc/clk?jk=def456&from=ja>
"""

GLASSDOOR_BODY = """\
Jobs for you

Data Engineer
Epsilon Analytics
Remote - Malaysia
<https://www.glassdoor.com/job-listing/data-engineer-JV_123.htm?src=alert>
"""


def test_parse_linkedin_digest():
    out = jobs.parse_digest("linkedin.com", LINKEDIN_BODY)
    assert len(out) == 2
    a = out[0]
    assert a["title"] == "Software Engineer"
    assert a["company"] == "Acme Sdn Bhd"
    assert a["location"] == "Kuala Lumpur, Malaysia"
    assert a["remote"] == "remote"
    assert a["link"] == "https://www.linkedin.com/comm/jobs/view/4012345678"
    assert a["source"] == "linkedin.com"
    b = out[1]
    assert b["title"] == "Junior Backend Developer"
    assert b["company"] == "Beta Tech"
    assert b["remote"] == ""


def test_parse_linkedin_strips_tracking_query():
    out = jobs.parse_digest("linkedin.com", LINKEDIN_BODY)
    assert all("?" not in p["link"] for p in out)


def test_parse_indeed_digest():
    out = jobs.parse_digest("indeed.com", INDEED_BODY)
    assert len(out) == 2
    a = out[0]
    assert a["title"] == "Full Stack Developer"
    assert a["company"] == "Gamma Solutions"
    assert a["location"] == "Kuala Lumpur"
    assert a["link"] == "https://my.indeed.com/rc/clk?jk=abc123&from=ja"
    b = out[1]
    assert b["title"] == "DevOps Engineer (Hybrid)"
    assert b["remote"] == "hybrid"


def test_parse_glassdoor_digest():
    out = jobs.parse_digest("glassdoor.com", GLASSDOOR_BODY)
    assert len(out) == 1
    assert out[0]["title"] == "Data Engineer"
    assert out[0]["company"] == "Epsilon Analytics"
    assert out[0]["remote"] == "remote"


def test_parse_digest_unknown_source():
    assert jobs.parse_digest("example.com", LINKEDIN_BODY) == []


def test_parse_digest_duplicate_link_once():
    body = ("Software Engineer\nAcme · KL\n"
            "View job <https://www.linkedin.com/comm/jobs/view/1?a=1>\n"
            "Same again\nAcme · KL\n"
            "View job <https://www.linkedin.com/comm/jobs/view/1?a=2>\n")
    out = jobs.parse_digest("linkedin.com", body)
    assert len(out) == 1


def test_parse_digest_link_without_title_skipped():
    body = "<https://www.linkedin.com/comm/jobs/view/1>\n"
    assert jobs.parse_digest("linkedin.com", body) == []


def test_parse_digest_garbage_returns_empty():
    assert jobs.parse_digest("linkedin.com", "hello\nworld\n") == []


def test_match_sender():
    senders = ["linkedin.com", "indeed.com", "glassdoor.com"]
    assert jobs.match_sender(
        "LinkedIn Job Alerts <jobalerts-noreply@linkedin.com>", senders) == "linkedin.com"
    assert jobs.match_sender(
        "Indeed <alert@match.indeed.com>", senders) == "indeed.com"   # subdomain
    assert jobs.match_sender("Mom <mom@example.com>", senders) is None
    assert jobs.match_sender("", senders) is None
    assert jobs.match_sender("no-angle-brackets", senders) is None


def test_parse_digest_normalizes_onsite():
    body = ("QA Engineer (On-site)\n"
            "Zeta Labs · Kuala Lumpur (On-site)\n"
            "View job <https://www.linkedin.com/comm/jobs/view/777>\n")
    out = jobs.parse_digest("linkedin.com", body)
    assert len(out) == 1
    assert out[0]["remote"] == "onsite"
    assert out[0]["location"] == "Kuala Lumpur"   # trailing (On-site) stripped
