"""voice/ui_server.py -- GET /cmd/google/status and POST /cmd/google/reconnect,
backing the orb Calendar tab's per-account reconnect card. google_auth is
mocked so no token files are read and no browser consent flow runs."""
from __future__ import annotations

import sys
from pathlib import Path

from fastapi.testclient import TestClient

from voice import ui_server


def _import_google_auth():
    repo_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo_root / ".claude" / "scripts"))
    from integrations import google_auth  # type: ignore
    return google_auth


def _hdr():
    return {"X-Vesper-Token": ui_server.TOKEN}


def test_status_lists_every_account(monkeypatch):
    m = _import_google_auth()
    monkeypatch.setattr(m, "list_accounts", lambda: [None, "jobs"])
    monkeypatch.setattr(m, "account_status", lambda account=None: {
        "account": account or "primary",
        "connected": account is None,
        "needs_reconnect": account is not None,
        "detail": "connected" if account is None else "sign-in expired",
    })
    client = TestClient(ui_server.app)
    r = client.get("/cmd/google/status")
    assert r.status_code == 200
    accounts = r.json()["accounts"]
    assert [a["account"] for a in accounts] == ["primary", "jobs"]
    assert accounts[0]["connected"] is True
    assert accounts[1]["needs_reconnect"] is True


def test_reconnect_primary_maps_to_none_and_returns_reauth_result(monkeypatch):
    m = _import_google_auth()
    seen = {}

    def _reauth(account=None):
        seen["account"] = account
        return {"ok": True, "account": account or "primary"}

    monkeypatch.setattr(m, "reauth", _reauth)
    client = TestClient(ui_server.app)
    r = client.post("/cmd/google/reconnect", headers=_hdr(), json={"account": "primary"})
    assert r.status_code == 200
    assert r.json() == {"ok": True, "account": "primary"}
    assert seen["account"] is None


def test_reconnect_labelled_account_passes_label_through(monkeypatch):
    m = _import_google_auth()
    seen = {}

    def _reauth(account=None):
        seen["account"] = account
        return {"ok": True, "account": account}

    monkeypatch.setattr(m, "reauth", _reauth)
    client = TestClient(ui_server.app)
    r = client.post("/cmd/google/reconnect", headers=_hdr(), json={"account": "jobs"})
    assert r.status_code == 200
    assert seen["account"] == "jobs"


def test_reconnect_requires_token(monkeypatch):
    m = _import_google_auth()
    monkeypatch.setattr(m, "reauth", lambda account=None: {"ok": True, "account": "primary"})
    client = TestClient(ui_server.app)
    r = client.post("/cmd/google/reconnect", json={"account": "primary"})
    assert r.status_code == 401


def test_reconnect_surfaces_failure(monkeypatch):
    m = _import_google_auth()
    monkeypatch.setattr(m, "reauth", lambda account=None: {
        "ok": False, "account": "primary", "error": "consent window closed"})
    client = TestClient(ui_server.app)
    r = client.post("/cmd/google/reconnect", headers=_hdr(), json={"account": "primary"})
    assert r.status_code == 200
    assert r.json()["ok"] is False
    assert "consent" in r.json()["error"]
