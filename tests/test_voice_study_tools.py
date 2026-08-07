"""voice/tools/study.py — review_cards / grade_card_tool voice tools."""
from __future__ import annotations

import json
from datetime import date

from voice import config as cfg
from voice import spaced_repetition as sr


def _env(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "get_data_dir", lambda: tmp_path)


def test_review_cards_returns_due_cards(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    from voice.tools.study import review_cards
    sr.add_cards("CS101", [{"q": "Q1", "a": "A1", "level": "recall"}], today=date(2026, 7, 7))
    result = json.loads(review_cards())
    assert len(result["cards"]) == 1
    assert result["cards"][0]["q"] == "Q1"


def test_review_cards_caps_at_ten(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    from voice.tools.study import review_cards
    many = [{"q": f"Q{i}", "a": f"A{i}", "level": "recall"} for i in range(15)]
    sr.add_cards("CS101", many, today=date(2026, 7, 7))
    result = json.loads(review_cards())
    assert len(result["cards"]) == 10


def test_grade_card_tool_marks_correct(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    from voice.tools.study import grade_card_tool, review_cards
    sr.add_cards("CS101", [{"q": "Q1", "a": "A1", "level": "recall"}], today=date(2026, 7, 7))
    card_id = json.loads(review_cards())["cards"][0]["id"]
    result = json.loads(grade_card_tool(card_id, True))
    assert result["status"] == "ok"
    assert json.loads(review_cards())["cards"] == []  # no longer due today


def test_tools_registered_in_dispatch():
    from voice.tools import REGISTRY
    names = {t["name"] for t in REGISTRY}
    assert "review_cards" in names
    assert "grade_card" in names
