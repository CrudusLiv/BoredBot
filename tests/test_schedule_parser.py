# tests/test_schedule_parser.py
"""Tests for schedule_parser module."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".claude" / "scripts"))

import schedule_parser

_SAMPLE_ENTRIES = [
    {"course": "CS101", "days": ["Mon", "Wed", "Fri"], "start": "08:00", "end": "09:30",
     "type": "lecture", "location": "EMPH"},
    {"course": "MAT101", "days": ["Tue", "Thu"], "start": "10:00", "end": "11:30",
     "type": "class", "location": ""},
]

_LOCATED_ENTRIES = [
    {"course": "CS101", "days": ["Mon"], "start": "08:00", "end": "09:30",
     "type": "lecture", "location": "Room A1"},
    {"course": "CS101", "days": ["Wed"], "start": "08:00", "end": "09:30",
     "type": "lecture", "location": "Online"},
]

_EMBED_ENTRIES = [
    {"course": "CS101", "days": ["Mon", "Wed"], "start": "08:00", "end": "09:30",
     "type": "lecture", "location": "EMPH"},
    {"course": "MAT101", "days": ["Mon", "Fri"], "start": "14:00", "end": "15:30",
     "type": "lecture", "location": "ALH2"},
    {"course": "CS201", "days": ["Tue", "Thu"], "start": "10:00", "end": "11:30",
     "type": "tutorial", "location": "BLH2"},
]


# --- parse_timetable (unchanged) ---

def test_parse_timetable_returns_entries_and_summary():
    with patch("schedule_parser.llm.call_json", return_value=_SAMPLE_ENTRIES):
        entries, summary = schedule_parser.parse_timetable("some timetable")
    assert entries == _SAMPLE_ENTRIES
    assert "CS101" in summary
    assert "Mon/Wed/Fri" in summary
    assert "MAT101" in summary
    assert "Tue/Thu" in summary


def test_parse_timetable_raises_on_llm_none():
    with patch("schedule_parser.llm.call_json", return_value=None):
        with pytest.raises(ValueError, match="empty or malformed"):
            schedule_parser.parse_timetable("bad text")


def test_parse_timetable_raises_on_empty_list():
    with patch("schedule_parser.llm.call_json", return_value=[]):
        with pytest.raises(ValueError):
            schedule_parser.parse_timetable("empty")


def test_parse_timetable_raises_on_malformed_entries():
    with patch("schedule_parser.llm.call_json", return_value=[{}]):
        with pytest.raises(ValueError):
            schedule_parser.parse_timetable("bad entries")


# --- write_schedule ---

def test_write_schedule_creates_file(tmp_vault):
    schedule_parser.write_schedule(_SAMPLE_ENTRIES)
    assert (tmp_vault / "SCHEDULE.md").exists()


def test_write_schedule_fresh_uses_tbd_semester(tmp_vault):
    schedule_parser.write_schedule(_SAMPLE_ENTRIES)
    content = (tmp_vault / "SCHEDULE.md").read_text(encoding="utf-8")
    assert "semester: TBD" in content


def test_write_schedule_sets_updated_today(tmp_vault):
    from datetime import date
    schedule_parser.write_schedule(_SAMPLE_ENTRIES)
    content = (tmp_vault / "SCHEDULE.md").read_text(encoding="utf-8")
    assert f"updated: {date.today().isoformat()}" in content


def test_write_schedule_preserves_semester_on_overwrite(tmp_vault):
    (tmp_vault / "SCHEDULE.md").write_text(
        "---\nsemester: 2026-S1\nupdated: 2026-01-01\n---\n\n| Course |\n",
        encoding="utf-8",
    )
    schedule_parser.write_schedule(_SAMPLE_ENTRIES)
    content = (tmp_vault / "SCHEDULE.md").read_text(encoding="utf-8")
    assert "semester: 2026-S1" in content


def test_write_schedule_flat_table_has_header_row(tmp_vault):
    schedule_parser.write_schedule(_SAMPLE_ENTRIES)
    content = (tmp_vault / "SCHEDULE.md").read_text(encoding="utf-8")
    assert "| Course | Type | Day | Start | End | Room |" in content


def test_write_schedule_flat_table_one_row_per_occurrence(tmp_vault):
    schedule_parser.write_schedule(_SAMPLE_ENTRIES)
    content = (tmp_vault / "SCHEDULE.md").read_text(encoding="utf-8")
    # CS101 Mon+Wed+Fri = 3 rows; MAT101 Tue+Thu = 2 rows; total 5
    data_rows = [ln for ln in content.splitlines()
                 if ln.startswith("| CS") or ln.startswith("| MAT")]
    assert len(data_rows) == 5


def test_write_schedule_sorts_by_day_then_time(tmp_vault):
    schedule_parser.write_schedule(_SAMPLE_ENTRIES)
    content = (tmp_vault / "SCHEDULE.md").read_text(encoding="utf-8")
    rows = [ln for ln in content.splitlines()
            if ln.startswith("| CS") or ln.startswith("| MAT")]
    assert "| Mon |" in rows[0] and "| 08:00 |" in rows[0]
    assert "| Tue |" in rows[1] and "| 10:00 |" in rows[1]


def test_write_schedule_no_old_format_artifacts(tmp_vault):
    schedule_parser.write_schedule(_SAMPLE_ENTRIES)
    content = (tmp_vault / "SCHEDULE.md").read_text(encoding="utf-8")
    assert "[!tip]" not in content
    assert "[!example]" not in content
    assert "<br>" not in content
    assert "— free" not in content


def test_write_schedule_includes_location(tmp_vault):
    schedule_parser.write_schedule(_LOCATED_ENTRIES)
    content = (tmp_vault / "SCHEDULE.md").read_text(encoding="utf-8")
    assert "| Room A1 |" in content
    assert "| Online |" in content


# --- has_existing_schedule ---

def test_has_existing_schedule_false_when_file_missing(tmp_vault):
    assert schedule_parser.has_existing_schedule() is False


def test_has_existing_schedule_false_when_no_table_header(tmp_vault):
    (tmp_vault / "SCHEDULE.md").write_text(
        "---\nsemester: TBD\n---\n\n<!-- placeholder -->\n",
        encoding="utf-8",
    )
    assert schedule_parser.has_existing_schedule() is False


def test_has_existing_schedule_true_after_write(tmp_vault):
    schedule_parser.write_schedule(_SAMPLE_ENTRIES)
    assert schedule_parser.has_existing_schedule() is True


# --- schedule_view ---

def test_schedule_view_none_when_missing(tmp_vault):
    assert schedule_parser.schedule_view() is None


def test_schedule_view_returns_entries_list(tmp_vault):
    schedule_parser.write_schedule(_SAMPLE_ENTRIES)
    view = schedule_parser.schedule_view()
    assert view is not None
    assert view["semester"] == "TBD"
    assert isinstance(view["entries"], list)
    assert len(view["entries"]) == 5  # 3 CS101 + 2 MAT101


def test_schedule_view_entry_shape(tmp_vault):
    schedule_parser.write_schedule(_SAMPLE_ENTRIES)
    view = schedule_parser.schedule_view()
    entry = view["entries"][0]
    assert set(entry) >= {"course", "type", "day", "start", "end", "location"}


def test_schedule_view_entries_sorted(tmp_vault):
    schedule_parser.write_schedule(_SAMPLE_ENTRIES)
    entries = schedule_parser.schedule_view()["entries"]
    assert entries[0]["day"] == "Mon" and entries[0]["course"] == "CS101"
    assert entries[1]["day"] == "Tue" and entries[1]["course"] == "MAT101"


# --- schedule_embeds ---

def test_schedule_embeds_titles_in_weekday_order(tmp_vault):
    schedule_parser.write_schedule(_EMBED_ENTRIES)
    view = schedule_parser.schedule_view()
    embeds = schedule_parser.schedule_embeds(view)
    assert [e["title"] for e in embeds] == ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]


def test_schedule_embeds_footer_on_last_only(tmp_vault):
    schedule_parser.write_schedule(_EMBED_ENTRIES)
    view = schedule_parser.schedule_view()
    embeds = schedule_parser.schedule_embeds(view)
    assert embeds[-1]["footer"] is not None
    for e in embeds[:-1]:
        assert e["footer"] is None


def test_schedule_embeds_line_contains_time_range(tmp_vault):
    schedule_parser.write_schedule(_EMBED_ENTRIES)
    view = schedule_parser.schedule_view()
    embeds = schedule_parser.schedule_embeds(view)
    monday = next(e for e in embeds if e["title"] == "Monday")
    assert any("08:00–09:30" in ln for ln in monday["lines"])
    assert any("14:00–15:30" in ln for ln in monday["lines"])


def test_schedule_embeds_color_is_integer(tmp_vault):
    schedule_parser.write_schedule(_EMBED_ENTRIES)
    view = schedule_parser.schedule_view()
    embeds = schedule_parser.schedule_embeds(view)
    for e in embeds:
        assert isinstance(e["color"], int)


def test_schedule_embeds_empty_when_no_entries(tmp_vault):
    view = {"semester": "TBD", "updated": "2026-01-01", "entries": []}
    assert schedule_parser.schedule_embeds(view) == []


# --- pending roundtrip (unchanged) ---

def test_read_pending_returns_none_when_missing(tmp_vault):
    assert schedule_parser.read_pending() is None


def test_write_and_read_pending_roundtrip(tmp_vault):
    schedule_parser.write_pending(_SAMPLE_ENTRIES)
    result = schedule_parser.read_pending()
    assert result == _SAMPLE_ENTRIES


def test_clear_pending_removes_file(tmp_vault):
    schedule_parser.write_pending(_SAMPLE_ENTRIES)
    schedule_parser.clear_pending()
    assert schedule_parser.read_pending() is None


def test_read_pending_returns_none_on_malformed_json(tmp_vault):
    path = schedule_parser._pending_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("not json", encoding="utf-8")
    assert schedule_parser.read_pending() is None


def test_clear_pending_is_idempotent_when_missing(tmp_vault):
    schedule_parser.clear_pending()
