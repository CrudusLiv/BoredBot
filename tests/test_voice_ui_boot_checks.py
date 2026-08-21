# tests/test_voice_ui_boot_checks.py
"""GET /cmd/boot-checks -- shape and failure isolation."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _no_live_llm_probe(monkeypatch):
    """_llm() calls voice.llm.get_status(), which auto-detects the backend by
    opening a live socket to localhost (Ollama/LM Studio). In sandboxed or
    firewalled environments that connect can hang well past its own declared
    timeout, taking the whole test run down with it -- stub it so boot-check
    tests never touch the network."""
    from voice import llm

    monkeypatch.setattr(
        llm, "get_status",
        lambda: {"backend": "claude_cli", "model": "sonnet", "available": True},
    )


@pytest.fixture
def client():
    from voice import ui_server
    return TestClient(ui_server.app)


def test_returns_checks_list(client):
    resp = client.get("/cmd/boot-checks")
    assert resp.status_code == 200
    checks = resp.json()["checks"]
    assert checks and isinstance(checks, list)


def test_each_check_has_the_full_shape(client):
    for row in client.get("/cmd/boot-checks").json()["checks"]:
        assert set(row) == {"id", "label", "detail", "status", "error"}


def test_one_raising_probe_does_not_500(client, monkeypatch):
    from voice import boot_checks

    def boom():
        raise RuntimeError("kaboom")

    monkeypatch.setitem(boot_checks.PROBES, "llm", ("LLM", boom))
    resp = client.get("/cmd/boot-checks")
    assert resp.status_code == 200
    rows = {r["id"]: r for r in resp.json()["checks"]}
    assert rows["llm"]["status"] == "fail"
    assert "kaboom" in rows["llm"]["error"]
