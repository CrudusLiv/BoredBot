"""detect_deadlines for voice/university_intake.py."""
from __future__ import annotations

from datetime import date
from pathlib import Path

from voice.university_intake import ParsedPath, detect_deadlines

TODAY = date(2026, 9, 3)


def _parsed(category="assignment", sub="Brief.pdf"):
    return ParsedPath("assignment" if category == "assignment" else "tutorial",
                      "Degree", 2, "BIT216", sub, Path("D:/U/x/" + sub))


def test_detects_slash_date():
    pairs = detect_deadlines("Submission due 15/10/2026 via Turnitin.", _parsed(), TODAY)
    assert pairs == [("2026-10-15", "BIT216 — Brief")]


def test_detects_month_name_date():
    pairs = detect_deadlines("Deadline: 5 December 2026.", _parsed(), TODAY)
    assert pairs == [("2026-12-05", "BIT216 — Brief")]


def test_ignores_tutorial_category():
    assert detect_deadlines("due 15/10/2026", _parsed("tutorial"), TODAY) == []


def test_ignores_past_and_far_future():
    assert detect_deadlines("due 01/01/2020 and due 01/01/2099", _parsed(), TODAY) == []


def test_caps_at_two():
    txt = "due 10/10/2026 due 11/10/2026 due 12/10/2026 due 13/10/2026"
    assert len(detect_deadlines(txt, _parsed(), TODAY)) == 2


def test_requires_keyword_near_date():
    assert detect_deadlines("The module covers 15/10/2026 historically.", _parsed(), TODAY) == []


def test_pairs_follow_document_order_not_regex_family_order():
    # A month-name date precedes an ISO date in the text. Family iteration
    # order would surface the ISO one first; document order must not.
    txt = "Submit by 5 December 2026. Second deadline 2026-10-01 firm."
    pairs = detect_deadlines(txt, _parsed(), TODAY)
    assert pairs == [
        ("2026-12-05", "BIT216 — Brief"),
        ("2026-10-01", "BIT216 — Brief"),
    ]
