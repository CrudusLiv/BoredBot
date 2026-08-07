"""Tests for vault/daily.py — single writer for the daily note."""
from __future__ import annotations

import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".claude" / "scripts"))

import vault.daily as daily_mod


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _daily_file(tmp_vault) -> Path:
    return tmp_vault / "daily" / f"{_today()}.md"


# --- append_line ---

def test_append_line_creates_file_with_header(tmp_vault):
    daily_mod.append_line("Habit: Lecture engagement")
    target = _daily_file(tmp_vault)
    assert target.exists()
    assert target.read_text(encoding="utf-8").startswith(f"# {_today()}")


def test_append_line_has_timestamp_format(tmp_vault):
    daily_mod.append_line("Habit: Lecture engagement")
    text = _daily_file(tmp_vault).read_text(encoding="utf-8")
    assert re.search(r"\[\d{2}:\d{2}\] Habit: Lecture engagement", text)


def test_append_line_appends_multiple_no_duplicate_header(tmp_vault):
    daily_mod.append_line("first")
    daily_mod.append_line("second")
    text = _daily_file(tmp_vault).read_text(encoding="utf-8")
    assert "first" in text
    assert "second" in text
    assert text.count(f"# {_today()}") == 1


# --- append_block ---

def test_append_block_creates_file(tmp_vault):
    daily_mod.append_block("Pre-compact flush (exit)", "### Decisions\n- x")
    target = _daily_file(tmp_vault)
    assert target.exists()
    text = target.read_text(encoding="utf-8")
    assert "Pre-compact flush (exit)" in text
    assert "### Decisions" in text


def test_append_block_format(tmp_vault):
    daily_mod.append_block("Session end (exit)", "### Decisions\n- x")
    text = _daily_file(tmp_vault).read_text(encoding="utf-8")
    assert re.search(r"## \[\d{2}:\d{2}\] Session end \(exit\)", text)


def test_append_block_appends_multiple_no_duplicate_header(tmp_vault):
    daily_mod.append_block("block one", "content a")
    daily_mod.append_block("block two", "content b")
    text = _daily_file(tmp_vault).read_text(encoding="utf-8")
    assert "block one" in text and "block two" in text
    assert text.count(f"# {_today()}") == 1


def test_append_line_and_block_coexist(tmp_vault):
    daily_mod.append_line("Habit: Lecture engagement")
    daily_mod.append_block("Pre-compact flush (exit)", "### Decisions\n- x")
    text = _daily_file(tmp_vault).read_text(encoding="utf-8")
    assert "Habit: Lecture engagement" in text
    assert "Pre-compact flush (exit)" in text


# --- CLI ---

def test_cli_habit(tmp_vault, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["daily.py", "habit", "Lecture engagement"])
    daily_mod._cli()
    assert "Habit: Lecture engagement" in _daily_file(tmp_vault).read_text(encoding="utf-8")


def test_cli_commit_assignment(tmp_vault, monkeypatch):
    monkeypatch.setattr(sys, "argv",
        ["daily.py", "commit", "assignment", "CrudusLiv/Vesper", "fix auth bug"])
    daily_mod._cli()
    assert "Commit [assignment]: CrudusLiv/Vesper — fix auth bug" in \
        _daily_file(tmp_vault).read_text(encoding="utf-8")


def test_cli_commit_personal(tmp_vault, monkeypatch):
    monkeypatch.setattr(sys, "argv",
        ["daily.py", "commit", "personal", "CrudusLiv/myrepo", "update readme"])
    daily_mod._cli()
    assert "Commit [personal]: CrudusLiv/myrepo — update readme" in \
        _daily_file(tmp_vault).read_text(encoding="utf-8")


def test_cli_lecture(tmp_vault, monkeypatch):
    monkeypatch.setattr(sys, "argv", [
        "daily.py", "lecture", "CS101", "Sorting Algorithms",
        "lectures/CS101/2026-05-28_sorting",
    ])
    daily_mod._cli()
    assert "Lecture: CS101 — Sorting Algorithms → [[lectures/CS101/2026-05-28_sorting]]" in \
        _daily_file(tmp_vault).read_text(encoding="utf-8")


def test_cli_alert(tmp_vault, monkeypatch):
    monkeypatch.setattr(sys, "argv",
        ["daily.py", "alert", "New Discord DM", "someone replied in #general"])
    daily_mod._cli()
    assert "Alert: New Discord DM — someone replied in #general" in \
        _daily_file(tmp_vault).read_text(encoding="utf-8")


# --- _lib delegation ---

def test_lib_append_to_daily_delegates_to_vault_daily(tmp_vault):
    """_lib.append_to_daily must produce the same file as vault/daily.append_block."""
    import importlib
    sys.path.insert(0, str(ROOT / ".claude" / "hooks"))
    import _lib  # type: ignore
    importlib.reload(_lib)  # re-derives PROJECT_DIR with CLAUDE_PROJECT_DIR set

    _lib.append_to_daily("### Decisions\n- x", "Pre-compact flush (exit)")
    text = _daily_file(tmp_vault).read_text(encoding="utf-8")
    assert "Pre-compact flush (exit)" in text
    assert "### Decisions" in text
    assert re.search(r"## \[\d{2}:\d{2}\] Pre-compact flush \(exit\)", text)
