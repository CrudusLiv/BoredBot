"""Jobs panel endpoint tests — FastAPI TestClient, LLM/drafter mocked."""
from fastapi.testclient import TestClient

import pytest

from voice import config as cfg
from voice import jobs


P1 = {"title": "Software Engineer", "company": "Acme", "location": "KL",
      "remote": "remote", "link": "https://x.com/j/1", "source": "linkedin.com"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    from voice import ui_server
    monkeypatch.setattr(cfg, "get_data_dir", lambda: tmp_path)
    monkeypatch.setattr(cfg, "save", lambda updates: None)   # don't touch %APPDATA%
    monkeypatch.setattr(ui_server, "TOKEN", "t")
    jobs.add_postings(tmp_path, [P1])
    return TestClient(ui_server.app), tmp_path


def _jid():
    return jobs.job_id(P1["link"])


def test_jobs_list(client):
    c, _ = client
    r = c.get("/cmd/jobs/list")
    assert r.status_code == 200
    rows = r.json()["jobs"]
    assert len(rows) == 1 and rows[0]["company"] == "Acme"


def test_jobs_update_status(client):
    c, tmp = client
    r = c.post("/cmd/jobs/update", json={"id": _jid(), "status": "applied"},
               headers={"X-Vesper-Token": "t"})
    assert r.status_code == 200 and r.json()["ok"] is True
    assert jobs.get_job(tmp, _jid())["status"] == "applied"


def test_jobs_update_invalid_status(client):
    c, _ = client
    r = c.post("/cmd/jobs/update", json={"id": _jid(), "status": "hired"},
               headers={"X-Vesper-Token": "t"})
    assert r.status_code == 400


def test_jobs_update_unknown_id(client):
    c, _ = client
    r = c.post("/cmd/jobs/update", json={"id": "nope", "status": "applied"},
               headers={"X-Vesper-Token": "t"})
    assert r.status_code == 404


def test_jobs_update_requires_token(client):
    c, _ = client
    r = c.post("/cmd/jobs/update", json={"id": _jid(), "status": "applied"})
    assert r.status_code == 401


def test_jobs_draft_ok(client, monkeypatch):
    c, _ = client
    monkeypatch.setattr(jobs, "draft_application",
                        lambda jid: {"ok": True, "name": "acme-software-engineer.md"})
    r = c.post("/cmd/jobs/draft", json={"id": _jid()},
               headers={"X-Vesper-Token": "t"})
    assert r.status_code == 200
    assert r.json()["name"] == "acme-software-engineer.md"


def test_jobs_draft_error_maps_to_400(client, monkeypatch):
    c, _ = client
    monkeypatch.setattr(jobs, "draft_application",
                        lambda jid: {"ok": False, "error": "RESUME.md is missing"})
    r = c.post("/cmd/jobs/draft", json={"id": _jid()},
               headers={"X-Vesper-Token": "t"})
    assert r.status_code == 400 and "RESUME.md" in r.json()["error"]


def test_jobs_draft_requires_token(client):
    c, _ = client
    r = c.post("/cmd/jobs/draft", json={"id": _jid()})
    assert r.status_code == 401


def test_settings_allow_job_keys(client):
    c, _ = client
    for key, value in [("job_alerts_enabled", True),
                       ("job_alert_senders", ["linkedin.com"]),
                       ("job_alert_lookback_days", 7)]:
        r = c.post("/cmd/settings", json={"key": key, "value": value},
                   headers={"X-Vesper-Token": "t"})
        assert r.status_code == 200, key
