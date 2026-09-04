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


# --- timeline nav block (graph-view chain) ---

def test_new_note_gets_timeline_block_linking_previous(tmp_vault):
    (tmp_vault / "daily" / "2020-01-01.md").write_text("# 2020-01-01\n", encoding="utf-8")
    daily_mod.append_block("Session end (exit)", "- x")
    text = _daily_file(tmp_vault).read_text(encoding="utf-8")
    assert "<!-- timeline:begin -->" in text
    assert "[[2020-01-01]]" in text


def test_previous_note_gains_forward_link_to_today(tmp_vault):
    prev = tmp_vault / "daily" / "2020-01-01.md"
    prev.write_text(
        "# 2020-01-01\n\n<!-- timeline:begin -->\n## Timeline\n← [[2019-12-31]]\n"
        "<!-- timeline:end -->\n\n## [09:00] old\n\nbody\n",
        encoding="utf-8",
    )
    daily_mod.append_line("first")
    ptext = prev.read_text(encoding="utf-8")
    assert f"[[{_today()}]]" in ptext
    assert "body" in ptext  # existing content preserved


def test_timeline_block_not_duplicated_on_same_day_appends(tmp_vault):
    (tmp_vault / "daily" / "2020-01-01.md").write_text("# 2020-01-01\n", encoding="utf-8")
    daily_mod.append_block("one", "a")
    daily_mod.append_line("two")
    daily_mod.append_block("three", "c")
    text = _daily_file(tmp_vault).read_text(encoding="utf-8")
    assert text.count("<!-- timeline:begin -->") == 1


# --- CLI ---

def test_cli_commit_work(tmp_vault, monkeypatch):
    monkeypatch.setattr(sys, "argv",
        ["daily.py", "commit", "work", "CrudusLiv/Vesper", "fix auth bug"])
    daily_mod._cli()
    assert "Commit [work]: CrudusLiv/Vesper — fix auth bug" in \
        _daily_file(tmp_vault).read_text(encoding="utf-8")


def test_cli_commit_personal(tmp_vault, monkeypatch):
    monkeypatch.setattr(sys, "argv",
        ["daily.py", "commit", "personal", "CrudusLiv/myrepo", "update readme"])
    daily_mod._cli()
    assert "Commit [personal]: CrudusLiv/myrepo — update readme" in \
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
