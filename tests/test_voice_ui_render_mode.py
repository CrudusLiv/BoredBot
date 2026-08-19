# tests/test_voice_ui_render_mode.py
"""Render-mode and face-asset config injected into the served orb page."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from voice import ui_server
    return TestClient(ui_server.app)


@pytest.fixture
def conf(monkeypatch):
    from voice import config as cfg

    def use(**over):
        monkeypatch.setattr(cfg, "load", lambda: {**cfg.DEFAULTS, **over})

    return use


def test_index_defaults_to_orb_mode(client, conf):
    conf()
    resp = client.get("/")
    assert 'const VESPER_RENDER_MODE = "orb";' in resp.text
    assert 'const VESPER_FACE_URL = "/static/face/vesper.png";' in resp.text


def test_index_honors_face_mode(client, conf):
    conf(ui_render_mode="face")
    assert 'const VESPER_RENDER_MODE = "face";' in client.get("/").text


def test_index_rejects_unknown_mode(client, conf):
    conf(ui_render_mode="bogus")
    assert 'const VESPER_RENDER_MODE = "orb";' in client.get("/").text


def test_avatar_mode_is_no_longer_accepted(client, conf):
    """The VRM path was removed; 'avatar' must fall back, not 404 a bundle."""
    conf(ui_render_mode="avatar")
    assert 'const VESPER_RENDER_MODE = "orb";' in client.get("/").text


def test_index_sanitizes_face_path_traversal(client, conf):
    conf(ui_face_png_path="../../../etc/passwd")
    assert 'const VESPER_FACE_URL = "/static/face/passwd";' in client.get("/").text


def test_face_mode_falls_back_to_orb_when_png_missing(client, conf):
    conf(ui_render_mode="face", ui_face_png_path="does_not_exist.png")
    assert 'const VESPER_RENDER_MODE = "orb";' in client.get("/").text


def test_missing_png_surfaces_as_a_boot_check(conf):
    from voice import boot_checks
    conf(ui_render_mode="face", ui_face_png_path="does_not_exist.png")
    rows = {r["id"]: r for r in boot_checks.run_all()}
    assert rows["face"]["status"] == "fail"


def test_face_mode_config_defaults():
    from voice import config as cfg
    assert cfg.DEFAULTS["ui_render_mode"] == "orb"
    assert cfg.DEFAULTS["ui_face_mode"] == "points"
    assert cfg.DEFAULTS["ui_face_point_count"] == 40000
