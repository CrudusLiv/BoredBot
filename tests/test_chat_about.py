"""Tests for chat/about.py — cross-session memory file loader/curator."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".claude"))

from chat import about  # noqa: E402


def test_load_about_returns_empty_when_missing(tmp_vault, monkeypatch):
    target = tmp_vault / "ABOUT.md"
    monkeypatch.setattr(about, "ABOUT_PATH", target)
    assert about.load_about() == ""


def test_load_about_returns_file_contents(tmp_vault, monkeypatch):
    target = tmp_vault / "ABOUT.md"
    target.write_text("# About CrudusLiv\n\n- prefers tea\n", encoding="utf-8")
    monkeypatch.setattr(about, "ABOUT_PATH", target)
    text = about.load_about()
    assert "prefers tea" in text


def test_append_bullet_adds_line_with_dash(tmp_vault, monkeypatch):
    target = tmp_vault / "ABOUT.md"
    target.write_text("# About CrudusLiv\n", encoding="utf-8")
    monkeypatch.setattr(about, "ABOUT_PATH", target)
    about.append_bullet("uses lowercase casually")
    assert "- uses lowercase casually" in target.read_text(encoding="utf-8")


def test_append_bullet_creates_file_if_missing(tmp_vault, monkeypatch):
    target = tmp_vault / "ABOUT.md"
    monkeypatch.setattr(about, "ABOUT_PATH", target)
    about.append_bullet("first fact")
    text = target.read_text(encoding="utf-8")
    assert text.startswith("# About CrudusLiv")
    assert "- first fact" in text


def test_append_bullet_dedupes(tmp_vault, monkeypatch):
    target = tmp_vault / "ABOUT.md"
    target.write_text("# About CrudusLiv\n\n- prefers tea\n", encoding="utf-8")
    monkeypatch.setattr(about, "ABOUT_PATH", target)
    about.append_bullet("prefers tea")
    text = target.read_text(encoding="utf-8")
    assert text.count("- prefers tea") == 1
