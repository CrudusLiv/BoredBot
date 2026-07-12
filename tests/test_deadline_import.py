"""voice/deadlines.py — GCal→DEADLINES.md import + mark-complete."""
from __future__ import annotations

from voice import deadlines as dl

MD = """# DEADLINES

## Format

To push a row to Google Calendar, leave it as-is. To opt out, prefix with `nogcal:`.

## Active

- nogcal: 2099-07-16 — MPU — Reflection submission
- 2099-08-01 — CS101 — Assignment 1
"""


def _ev(title, date="2099-07-20"):
    return {"summary": title, "start": date}


# ── filter_deadline_events ────────────────────────────────────────────────────

def test_filter_matches_keywords_case_insensitive():
    events = [_ev("FYP Submission"), _ev("Ginny bday"), _ev("CS101 EXAM")]
    out = dl.filter_deadline_events(events, dl.DEFAULT_KEYWORDS)
    assert [t for _, t in out] == ["FYP Submission", "CS101 EXAM"]


def test_filter_uses_word_boundaries():
    # "test" must not match "Contest"; "due" must not match "residue"
    events = [_ev("Contest stream"), _ev("Residue check"), _ev("Physics test")]
    out = dl.filter_deadline_events(events, dl.DEFAULT_KEYWORDS)
    assert [t for _, t in out] == ["Physics test"]


def test_filter_takes_date_prefix_of_datetime_start():
    out = dl.filter_deadline_events(
        [{"summary": "Quiz 2", "start": "2099-07-21T14:00:00+08:00"}],
        dl.DEFAULT_KEYWORDS,
    )
    assert out == [("2099-07-21", "Quiz 2")]


# ── merge_events ──────────────────────────────────────────────────────────────

def test_merge_appends_nogcal_row_under_active():
    text, added = dl.merge_events(MD, [("2099-07-20", "FYP Submission")])
    assert added == ["2099-07-20 — FYP Submission"]
    assert "- nogcal: 2099-07-20 — FYP Submission" in text
    # lands inside ## Active (before end of file / next section)
    assert text.index("## Active") < text.index("FYP Submission")


def test_merge_dedupes_against_existing_rows_either_prefix():
    text, added = dl.merge_events(MD, [
        ("2099-07-16", "MPU — Reflection submission"),   # nogcal row
        ("2099-08-01", "CS101 — Assignment 1"),          # plain row
        ("2099-08-01", "cs101 — assignment 1"),          # case variant
    ])
    assert added == []
    assert text == MD


def test_merge_dedupes_ignoring_punctuation():
    # Calendar titles are freeform; the row has an em-dash the event lacks.
    _, added = dl.merge_events(MD, [("2099-07-16", "MPU Reflection submission")])
    assert added == []


def test_merge_dedupes_against_done_section():
    md = MD + "\n## Done\n\n- nogcal: 2099-07-10 — Lab report ✓ done 2099-07-11\n"
    _, added = dl.merge_events(md, [("2099-07-10", "Lab report")])
    assert added == []


# ── complete ──────────────────────────────────────────────────────────────────

def test_complete_moves_row_to_done_with_stamp():
    text, row = dl.complete(MD, "reflection", today="2099-07-17")
    assert row == "- nogcal: 2099-07-16 — MPU — Reflection submission"
    active = text.split("## Done")[0]
    assert "Reflection submission" not in active
    assert "- nogcal: 2099-07-16 — MPU — Reflection submission ✓ done 2099-07-17" in text


def test_complete_no_match_returns_none_and_text_unchanged():
    text, row = dl.complete(MD, "nonexistent thing", today="2099-07-17")
    assert row is None
    assert text == MD


def test_complete_only_considers_active_rows():
    md = MD + "\n## Done\n\n- 2099-06-01 — Old — Past thing ✓ done 2099-06-02\n"
    text, row = dl.complete(md, "past thing", today="2099-07-17")
    assert row is None
    assert text == md
