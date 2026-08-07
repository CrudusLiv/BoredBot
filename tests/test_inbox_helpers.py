"""Tests for inbox.py extraction helpers."""
from __future__ import annotations

import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repo_root / ".claude" / "scripts"))

from core.inbox import _extract_study_card_count  # type: ignore  # noqa: E402


_SAMPLE_NOTE = """\
---
type: lecture
course: DIP215
---

# Lecture 3

## Key concepts
- Flow of control
- Boolean expressions

## Study cards
- Q: What is flow of control? | A: The order statements are processed
- Q: What does && mean?       | A: Logical AND
- Q: What is a switch?        | A: Multiway branch

## Open questions
- Why does fall-through exist?
"""


def test_extract_study_card_count_basic():
    assert _extract_study_card_count(_SAMPLE_NOTE) == 3


def test_extract_study_card_count_no_section():
    note = "# Title\n\n## Key concepts\n- A\n"
    assert _extract_study_card_count(note) == 0


def test_extract_study_card_count_empty_section():
    note = "# T\n\n## Study cards\n\n## Open questions\n"
    assert _extract_study_card_count(note) == 0


def test_extract_study_card_count_stops_at_next_heading():
    note = (
        "## Study cards\n"
        "- Q: one | A: 1\n"
        "- Q: two | A: 2\n"
        "## Another section\n"
        "- Q: not a card | A: x\n"
    )
    assert _extract_study_card_count(note) == 2


def test_extract_study_card_count_accepts_asterisk_and_unprefixed():
    note = (
        "## Study cards\n"
        "- Q: dash | A: 1\n"
        "* Q: star | A: 2\n"
        "Q: bare | A: 3\n"
    )
    assert _extract_study_card_count(note) == 3


def test_process_one_returns_roadmap_notice_instead_of_posting(monkeypatch):
    """_process_one's summary must carry roadmap_notice text; the Discord
    webhook function must no longer exist on the module."""
    from core import inbox

    monkeypatch.setattr(
        inbox, "_build_roadmap_notice",
        lambda lecture_data, roadmap_file: "Roadmap ready: CS101",
    )
    assert not hasattr(inbox, "_post_roadmap_embed")
