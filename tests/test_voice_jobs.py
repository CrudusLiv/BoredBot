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


# ---- scan_alerts ------------------------------------------------------------

class _FakeGmail:
    def __init__(self, msgs, bodies, fail_body_ids=()):
        self._msgs, self._bodies = msgs, bodies
        self._fail = set(fail_body_ids)
        self.list_calls = []

    def list_recent(self, days=7, max_results=30):
        self.list_calls.append({"days": days, "max_results": max_results})
        return self._msgs

    def get_body(self, msg_id):
        if msg_id in self._fail:
            raise RuntimeError("boom")
        return self._bodies.get(msg_id, "")


JOBS_CONF = {
    "job_alerts_enabled": True,
    "job_alert_senders": ["linkedin.com", "indeed.com", "glassdoor.com"],
    "job_alert_lookback_days": 3,
}


def _patch_gmail(monkeypatch, fake):
    import integrations.gmail_int as gi
    monkeypatch.setattr(gi, "list_recent", fake.list_recent)
    monkeypatch.setattr(gi, "get_body", fake.get_body)


def test_scan_alerts_adds_from_matching_sender(tmp_path, monkeypatch):
    fake = _FakeGmail(
        [{"id": "m1", "from": "LinkedIn Job Alerts <jobalerts-noreply@linkedin.com>"},
         {"id": "m2", "from": "Mom <mom@example.com>"}],
        {"m1": LINKEDIN_BODY},
    )
    _patch_gmail(monkeypatch, fake)
    added = jobs.scan_alerts(tmp_path, JOBS_CONF)
    assert added == 2
    assert fake.list_calls == [{"days": 3, "max_results": 50}]
    assert len(jobs.load_jobs(tmp_path)) == 2


def test_scan_alerts_one_bad_email_does_not_abort(tmp_path, monkeypatch):
    fake = _FakeGmail(
        [{"id": "bad", "from": "a@indeed.com"},
         {"id": "ok", "from": "b@linkedin.com"}],
        {"ok": LINKEDIN_BODY}, fail_body_ids={"bad"},
    )
    _patch_gmail(monkeypatch, fake)
    assert jobs.scan_alerts(tmp_path, JOBS_CONF) == 2   # 'ok' still parsed


def test_scan_alerts_second_pass_adds_nothing(tmp_path, monkeypatch):
    fake = _FakeGmail([{"id": "m1", "from": "x@linkedin.com"}], {"m1": LINKEDIN_BODY})
    _patch_gmail(monkeypatch, fake)
    assert jobs.scan_alerts(tmp_path, JOBS_CONF) == 2
    assert jobs.scan_alerts(tmp_path, JOBS_CONF) == 0


# ---- config defaults + heartbeat gate ----------------------------------------

from voice import config as cfg
from voice.heartbeat import Heartbeat


def test_config_job_alert_defaults():
    # assert on DEFAULTS, not load() — the installed user config merges into
    # load() and would make this flaky on a machine with the feature enabled
    assert cfg.DEFAULTS["job_alerts_enabled"] is False
    assert cfg.DEFAULTS["job_alert_senders"] == ["linkedin.com", "indeed.com", "glassdoor.com"]
    assert cfg.DEFAULTS["job_alert_lookback_days"] == 3


def _hb() -> Heartbeat:
    return Heartbeat(interval_minutes=30, idle_fn=lambda: None)


def test_check_job_alerts_disabled_no_scan(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "load", lambda: dict(JOBS_CONF, job_alerts_enabled=False))
    monkeypatch.setattr(cfg, "get_data_dir", lambda: tmp_path)
    calls = []
    monkeypatch.setattr(jobs, "scan_alerts", lambda *a: calls.append(a))
    _hb()._check_job_alerts()
    assert calls == []


def test_check_job_alerts_enabled_scans_silently(tmp_path, monkeypatch):
    import voice.heartbeat as hb_mod
    monkeypatch.setattr(cfg, "load", lambda: dict(JOBS_CONF))
    monkeypatch.setattr(cfg, "get_data_dir", lambda: tmp_path)
    posts = []
    monkeypatch.setattr(hb_mod, "_post",
                        lambda text, level="INFO", meta=None: posts.append(text))
    calls = []
    monkeypatch.setattr(jobs, "scan_alerts", lambda d, c: calls.append(d) or 5)
    _hb()._check_job_alerts()
    assert calls == [tmp_path]
    assert posts == []                    # silent: no notice even when jobs found


def test_check_job_alerts_survives_scan_error(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "load", lambda: dict(JOBS_CONF))
    monkeypatch.setattr(cfg, "get_data_dir", lambda: tmp_path)
    monkeypatch.setattr(jobs, "scan_alerts",
                        lambda *a: (_ for _ in ()).throw(RuntimeError("gmail down")))
    _hb()._check_job_alerts()             # must not raise


def test_check_job_alerts_registered_in_scheduled():
    hb = _hb()
    import inspect
    src = inspect.getsource(hb._run_scheduled)
    assert "_check_job_alerts" in src


# ---- draft_application --------------------------------------------------------

RESUME = "## Skills\nPython, FastAPI\n## Experience\nVesper (personal project)"


@pytest.fixture
def draft_env(tmp_path, monkeypatch):
    """Vault with a filled RESUME.md, one stored job, mocked LLM + write_draft."""
    vault = tmp_path / "vault"
    (vault / "profile").mkdir(parents=True)
    (vault / "profile" / "RESUME.md").write_text(RESUME, encoding="utf-8")
    monkeypatch.setattr(cfg, "get_data_dir", lambda: tmp_path)
    monkeypatch.setattr(cfg, "get_vault_dir", lambda: vault)
    jobs.add_postings(tmp_path, [P1])
    import voice.tools.workspace as ws
    writes: list[tuple] = []
    monkeypatch.setattr(ws, "write_draft",
                        lambda name, text: writes.append((name, text)) or
                        f"Wrote {len(text)} bytes to drafts/active/{name}.")
    llm_calls: list[dict] = []
    from voice import llm
    monkeypatch.setattr(llm, "call",
                        lambda prompt, **kw: llm_calls.append({"prompt": prompt, **kw})
                        or "Dear Hiring Manager, ...")
    return vault, writes, llm_calls


def test_draft_application_happy_path(draft_env, tmp_path):
    vault, writes, llm_calls = draft_env
    jid = jobs.job_id(P1["link"])
    res = jobs.draft_application(jid)
    assert res["ok"] is True
    assert res["name"] == "acme-software-engineer.md"
    assert writes and writes[0][0] == "acme-software-engineer.md"
    assert "Dear Hiring Manager" in writes[0][1]
    prompt = llm_calls[0]["prompt"]
    assert "Software Engineer" in prompt and "Python, FastAPI" in prompt
    assert jobs.get_job(tmp_path, jid)["status"] == "drafted"


def test_draft_application_unknown_id(draft_env):
    assert jobs.draft_application("nope") == {"ok": False, "error": "unknown job id"}


def test_draft_application_missing_resume(draft_env, tmp_path):
    vault, writes, _ = draft_env
    (vault / "profile" / "RESUME.md").unlink()
    res = jobs.draft_application(jobs.job_id(P1["link"]))
    assert res["ok"] is False
    assert "RESUME.md" in res["error"]
    assert writes == []                   # no file written
    assert jobs.get_job(tmp_path, jobs.job_id(P1["link"]))["status"] == "new"


def test_draft_application_empty_resume(draft_env, tmp_path):
    vault, writes, _ = draft_env
    (vault / "profile" / "RESUME.md").write_text("  \n", encoding="utf-8")
    res = jobs.draft_application(jobs.job_id(P1["link"]))
    assert res["ok"] is False and writes == []


def test_draft_application_llm_failure(draft_env, monkeypatch, tmp_path):
    vault, writes, _ = draft_env
    from voice import llm
    monkeypatch.setattr(llm, "call", lambda *a, **k: "")   # backend down
    res = jobs.draft_application(jobs.job_id(P1["link"]))
    assert res["ok"] is False and writes == []
    assert jobs.get_job(tmp_path, jobs.job_id(P1["link"]))["status"] == "new"
