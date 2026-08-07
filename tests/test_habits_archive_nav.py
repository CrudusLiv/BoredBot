"""Tests for habits archive nav footer and history link helpers."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".claude" / "scripts"))

import memory_reflect as mr


HABITS_TEMPLATE = """\
# HABITS

## History

_(Filled by the heartbeat. Newest at top.)_

- _(empty — no history yet)_
"""


def test_add_archive_nav_with_prev(tmp_path):
    archive = tmp_path / "2026-06-15.md"
    archive.write_text("# HABITS\n\ncontent\n", encoding="utf-8")
    mr._add_archive_nav(archive, "2026-06-14")
    text = archive.read_text(encoding="utf-8")
    assert "← [[goals/habits-history/2026-06-14|2026-06-14]]" in text
    assert "[[HABITS|all days]]" in text


def test_add_archive_nav_no_prev(tmp_path):
    archive = tmp_path / "2026-05-01.md"
    archive.write_text("# HABITS\n\ncontent\n", encoding="utf-8")
    mr._add_archive_nav(archive, None)
    text = archive.read_text(encoding="utf-8")
    assert "[[HABITS|all days]]" in text
    assert "←" not in text


def test_add_archive_nav_idempotent(tmp_path):
    archive = tmp_path / "2026-06-15.md"
    archive.write_text("# HABITS\n\n[[HABITS|all days]]\n", encoding="utf-8")
    mr._add_archive_nav(archive, "2026-06-14")
    text = archive.read_text(encoding="utf-8")
    assert text.count("[[HABITS|all days]]") == 1


def test_prepend_history_link_replaces_placeholder(tmp_vault, monkeypatch):
    habits_file = tmp_vault / "HABITS.md"
    habits_file.write_text(HABITS_TEMPLATE, encoding="utf-8")
    monkeypatch.setattr(mr, "HABITS", habits_file)
    mr._prepend_history_link("2026-06-15")
    text = habits_file.read_text(encoding="utf-8")
    assert "[[goals/habits-history/2026-06-15|2026-06-15]]" in text
    assert "_(empty — no history yet)_" not in text


def test_prepend_history_link_newest_first(tmp_vault, monkeypatch):
    habits_file = tmp_vault / "HABITS.md"
    habits_file.write_text(HABITS_TEMPLATE, encoding="utf-8")
    monkeypatch.setattr(mr, "HABITS", habits_file)
    mr._prepend_history_link("2026-06-14")
    mr._prepend_history_link("2026-06-15")
    text = habits_file.read_text(encoding="utf-8")
    pos_15 = text.index("2026-06-15")
    pos_14 = text.index("2026-06-14")
    assert pos_15 < pos_14


def test_prepend_history_link_no_marker(tmp_vault, monkeypatch):
    habits_file = tmp_vault / "HABITS.md"
    habits_file.write_text("# HABITS\n\nNo history section.\n", encoding="utf-8")
    monkeypatch.setattr(mr, "HABITS", habits_file)
    mr._prepend_history_link("2026-06-15")
    text = habits_file.read_text(encoding="utf-8")
    assert "2026-06-15" not in text
