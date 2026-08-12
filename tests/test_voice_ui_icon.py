"""voice/ui_server.py::get_icon -- GET /cmd/icon. icons.get_icon_png is
mocked; no real exe is ever touched."""
from __future__ import annotations

from fastapi.testclient import TestClient

from voice import ui_server
from voice.tools import icons


def test_icon_returns_png_bytes_with_cache_headers(monkeypatch):
    monkeypatch.setattr(icons, "get_icon_png", lambda target: b"\x89PNG\r\n\x1a\nFAKE")
    client = TestClient(ui_server.app)
    r = client.get("/cmd/icon", params={"target": "zoom.exe"})
    assert r.status_code == 200
    assert r.content == b"\x89PNG\r\n\x1a\nFAKE"
    assert r.headers["content-type"] == "image/png"
    assert "max-age=31536000" in r.headers["cache-control"]


def test_icon_returns_404_when_unresolvable(monkeypatch):
    monkeypatch.setattr(icons, "get_icon_png", lambda target: None)
    client = TestClient(ui_server.app)
    r = client.get("/cmd/icon", params={"target": "spotify:"})
    assert r.status_code == 404


def test_icon_passes_target_query_param_through(monkeypatch):
    captured = {}
    monkeypatch.setattr(icons, "get_icon_png", lambda target: captured.setdefault("target", target) or b"PNG")
    client = TestClient(ui_server.app)
    client.get("/cmd/icon", params={"target": "C:\\apps\\zoom.exe"})
    assert captured["target"] == "C:\\apps\\zoom.exe"
