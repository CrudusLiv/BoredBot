"""voice/spaced_repetition.py — Leitner-box card store."""
from __future__ import annotations

from datetime import date

from voice import config as cfg
from voice import spaced_repetition as sr


def _env(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "get_data_dir", lambda: tmp_path)


def test_add_cards_returns_count(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    n = sr.add_cards("CS101", [{"q": "What is a thread?", "a": "A unit of execution", "level": "recall"}])
    assert n == 1


def test_new_cards_are_due_immediately(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    sr.add_cards("CS101", [{"q": "Q1", "a": "A1", "level": "recall"}], today=date(2026, 7, 7))
    due = sr.due_cards(today=date(2026, 7, 7))
    assert len(due) == 1
    assert due[0]["course"] == "CS101"
    assert due[0]["box"] == 1


def test_grade_correct_advances_box_and_pushes_due_date(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    sr.add_cards("CS101", [{"q": "Q1", "a": "A1", "level": "recall"}], today=date(2026, 7, 7))
    card_id = sr.due_cards(today=date(2026, 7, 7))[0]["id"]
    sr.grade_card(card_id, correct=True, today=date(2026, 7, 7))
    assert sr.due_cards(today=date(2026, 7, 7)) == []          # not due same day
    assert len(sr.due_cards(today=date(2026, 7, 9))) == 1       # box 2 = +2 days


def test_grade_incorrect_resets_to_box_one_and_due_tomorrow(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    sr.add_cards("CS101", [{"q": "Q1", "a": "A1", "level": "recall"}], today=date(2026, 7, 7))
    card_id = sr.due_cards(today=date(2026, 7, 7))[0]["id"]
    sr.grade_card(card_id, correct=True, today=date(2026, 7, 7))   # box 2, due +2d
    sr.grade_card(card_id, correct=False, today=date(2026, 7, 9))  # wrong -> back to box 1
    due_tomorrow = sr.due_cards(today=date(2026, 7, 10))
    assert len(due_tomorrow) == 1
    assert due_tomorrow[0]["box"] == 1


def test_grade_unknown_card_id_is_a_noop(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    sr.grade_card("does-not-exist", correct=True)  # must not raise
