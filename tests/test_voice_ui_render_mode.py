# tests/test_voice_ui_render_mode.py
"""Tests for the render-mode/VRM-path config injected into the served orb page."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from voice import ui_server
    return TestClient(ui_server.app)


def test_index_defaults_to_orb_mode(client, monkeypatch):
    from voice import config as cfg
    monkeypatch.setattr(cfg, "load", lambda: {**cfg.DEFAULTS})
    resp = client.get("/")
    assert 'const VESPER_RENDER_MODE = "orb";' in resp.text
    assert 'const VESPER_AVATAR_VRM_URL = "/static/avatar/models/placeholder.vrm";' in resp.text


def test_index_honors_avatar_mode(client, monkeypatch):
    from voice import config as cfg
    monkeypatch.setattr(cfg, "load", lambda: {**cfg.DEFAULTS, "ui_render_mode": "avatar"})
    resp = client.get("/")
    assert 'const VESPER_RENDER_MODE = "avatar";' in resp.text


def test_index_rejects_unknown_mode(client, monkeypatch):
    from voice import config as cfg
    monkeypatch.setattr(cfg, "load", lambda: {**cfg.DEFAULTS, "ui_render_mode": "bogus"})
    resp = client.get("/")
    assert 'const VESPER_RENDER_MODE = "orb";' in resp.text


def test_index_sanitizes_vrm_path_traversal(client, monkeypatch):
    from voice import config as cfg
    monkeypatch.setattr(cfg, "load", lambda: {**cfg.DEFAULTS, "ui_avatar_vrm_path": "../../../etc/passwd"})
    resp = client.get("/")
    assert 'const VESPER_AVATAR_VRM_URL = "/static/avatar/models/passwd";' in resp.text
