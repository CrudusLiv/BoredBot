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
