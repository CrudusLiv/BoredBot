"""voice/ui_server.py::pc_control_discover_apps -- GET /cmd/pc-control/apps.
Read-only, no token required (matches /cmd/settings GET); the underlying
Start Menu scan is mocked so this never touches the real filesystem."""
from __future__ import annotations

from fastapi.testclient import TestClient

from voice import ui_server
from voice.tools import pc_control


def test_discover_apps_returns_scanned_list(monkeypatch):
    monkeypatch.setattr(pc_control, "discover_apps", lambda: [{"name": "spotify", "target": "C:\\Spotify.exe"}])
    client = TestClient(ui_server.app)
    r = client.get("/cmd/pc-control/apps")
    assert r.status_code == 200
    assert r.json()["apps"] == [{"name": "spotify", "target": "C:\\Spotify.exe"}]


def test_discover_apps_error_is_reported_not_unhandled(monkeypatch):
    def _boom():
        raise RuntimeError("scan failed")

    monkeypatch.setattr(pc_control, "discover_apps", _boom)
    client = TestClient(ui_server.app)
    r = client.get("/cmd/pc-control/apps")
    assert r.status_code == 500
    assert "error" in r.json()
