"""Tests for the three new auto-detection functions in habits.py."""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".claude" / "scripts"))

from core import habits

KL = timezone(timedelta(hours=8))


# ── _classes_done_today ──────────────────────────────────────────────────────

def test_classes_done_today_free_day(monkeypatch):
    monkeypatch.setattr(habits, "classes_today", lambda: [])
    assert habits._classes_done_today() is True


def test_classes_done_today_notes_taken(tmp_vault, monkeypatch):
    monkeypatch.setattr(habits, "classes_today", lambda: [{"end": "17:00"}])
    monkeypatch.setattr(habits, "LECTURES", tmp_vault / "lectures")
    (tmp_vault / "lectures" / "note.md").write_text("x", encoding="utf-8")
    assert habits._classes_done_today() is True


def test_classes_done_today_after_last_class(monkeypatch):
    monkeypatch.setattr(habits, "classes_today", lambda: [{"end": "17:00"}])
    monkeypatch.setattr(habits, "_lectures_touched_today", lambda: False)
    monkeypatch.setattr(habits, "_now_kl", lambda: datetime(2026, 6, 15, 18, 0, tzinfo=KL))
    assert habits._classes_done_today() is True


def test_classes_done_today_during_class(monkeypatch):
    monkeypatch.setattr(habits, "classes_today", lambda: [{"end": "17:00"}])
    monkeypatch.setattr(habits, "_lectures_touched_today", lambda: False)
    monkeypatch.setattr(habits, "_now_kl", lambda: datetime(2026, 6, 15, 10, 0, tzinfo=KL))
    assert habits._classes_done_today() is False


def test_classes_done_today_no_end_time(monkeypatch):
    """No parseable end times → cannot auto-check school day."""
    monkeypatch.setattr(habits, "classes_today", lambda: [{"end": ""}])
    monkeypatch.setattr(habits, "_lectures_touched_today", lambda: False)
    assert habits._classes_done_today() is False


# ── _sleep_morning_check ─────────────────────────────────────────────────────

def test_sleep_morning_check_after_7am(monkeypatch):
    monkeypatch.setattr(habits, "_now_kl", lambda: datetime(2026, 6, 15, 9, 0, tzinfo=KL))
    assert habits._sleep_morning_check() is True


def test_sleep_morning_check_before_7am(monkeypatch):
    monkeypatch.setattr(habits, "_now_kl", lambda: datetime(2026, 6, 15, 6, 59, tzinfo=KL))
    assert habits._sleep_morning_check() is False


# ── _finance_entry_today ─────────────────────────────────────────────────────

def test_finance_entry_today_file_modified(tmp_vault, monkeypatch):
    finance_file = tmp_vault / "finance" / "2026-06.md"
    finance_file.write_text("entry", encoding="utf-8")
    monkeypatch.setattr(habits, "VAULT", tmp_vault)
    monkeypatch.setattr(habits, "_today_kl", lambda: "2026-06-15")
    assert habits._finance_entry_today() is True


def test_finance_entry_today_no_file(tmp_vault, monkeypatch):
    monkeypatch.setattr(habits, "VAULT", tmp_vault)
    monkeypatch.setattr(habits, "_today_kl", lambda: "2026-06-15")
    assert habits._finance_entry_today() is False


# ── auto_check dispatch ───────────────────────────────────────────────────────

def test_auto_check_dispatches_classes_done_today(tmp_vault, monkeypatch):
    import vault.daily as daily_mod
    habits_text = "- [ ] **Classes**\n"
    (tmp_vault / "HABITS.md").write_text(habits_text, encoding="utf-8")
    monkeypatch.setattr(habits, "HABITS", tmp_vault / "HABITS.md")
    monkeypatch.setattr(habits, "_load_config", lambda: {
        "auto_detect": {"Classes": "classes_done_today"},
        "categories": {}, "category_emoji": {},
    })
    monkeypatch.setattr(habits, "_classes_done_today", lambda: True)
    monkeypatch.setattr(daily_mod, "append_line", lambda line: None)

    newly = habits.auto_check({})
    assert "Classes" in newly


def test_auto_check_dispatches_sleep_morning_check(tmp_vault, monkeypatch):
    import vault.daily as daily_mod
    habits_text = "- [ ] **Sleep**\n"
    (tmp_vault / "HABITS.md").write_text(habits_text, encoding="utf-8")
    monkeypatch.setattr(habits, "HABITS", tmp_vault / "HABITS.md")
    monkeypatch.setattr(habits, "_load_config", lambda: {
        "auto_detect": {"Sleep": "sleep_morning_check"},
        "categories": {}, "category_emoji": {},
    })
    monkeypatch.setattr(habits, "_sleep_morning_check", lambda: True)
    monkeypatch.setattr(daily_mod, "append_line", lambda line: None)

    newly = habits.auto_check({})
    assert "Sleep" in newly


def test_auto_check_dispatches_finance_entry_today(tmp_vault, monkeypatch):
    import vault.daily as daily_mod
    habits_text = "- [ ] **Budget**\n"
    (tmp_vault / "HABITS.md").write_text(habits_text, encoding="utf-8")
    monkeypatch.setattr(habits, "HABITS", tmp_vault / "HABITS.md")
    monkeypatch.setattr(habits, "_load_config", lambda: {
        "auto_detect": {"Budget": "finance_entry_today"},
        "categories": {}, "category_emoji": {},
    })
    monkeypatch.setattr(habits, "_finance_entry_today", lambda: True)
    monkeypatch.setattr(daily_mod, "append_line", lambda line: None)

    newly = habits.auto_check({})
    assert "Budget" in newly
