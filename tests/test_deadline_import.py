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
    events = [_ev("Passport Renewal"), _ev("Ginny bday"), _ev("Electric BILL")]
    out = dl.filter_deadline_events(events, dl.DEFAULT_KEYWORDS)
    assert [t for _, t in out] == ["Passport Renewal", "Electric BILL"]


def test_filter_uses_word_boundaries():
    # "bill" must not match "Billboard"; "due" must not match "residue"
    events = [_ev("Billboard shoot"), _ev("Residue check"), _ev("Phone bill")]
    out = dl.filter_deadline_events(events, dl.DEFAULT_KEYWORDS)
    assert [t for _, t in out] == ["Phone bill"]


def test_filter_takes_date_prefix_of_datetime_start():
    out = dl.filter_deadline_events(
        [{"summary": "Visa application", "start": "2099-07-21T14:00:00+08:00"}],
        dl.DEFAULT_KEYWORDS,
    )
    assert out == [("2099-07-21", "Visa application")]


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


# ── prune_deleted ────────────────────────────────────────────────────────────

def test_prune_removes_nogcal_row_whose_event_is_gone():
    # The MPU row is inside the fetch window but no calendar event matches
    # it any more -- the event was deleted from Google Calendar directly.
    text, removed = dl.prune_deleted(MD, [], dl.DEFAULT_KEYWORDS,
                                      window_start="2099-07-01", window_end="2099-08-31")
    assert removed == ["2099-07-16 — MPU — Reflection submission"]
    assert "Reflection submission" not in text
    # The plain (non-nogcal) row is left alone even though it's also unmatched.
    assert "CS101 — Assignment 1" in text


def test_prune_keeps_row_still_present_in_events():
    events = [_ev("MPU — Reflection submission", "2099-07-16")]
    text, removed = dl.prune_deleted(MD, events, dl.DEFAULT_KEYWORDS,
                                      window_start="2099-07-01", window_end="2099-08-31")
    assert removed == []
    assert text == MD


def test_prune_ignores_rows_outside_the_fetch_window():
    text, removed = dl.prune_deleted(MD, [], dl.DEFAULT_KEYWORDS,
                                      window_start="2099-07-17", window_end="2099-08-31")
    assert removed == []
    assert text == MD


def test_prune_never_touches_plain_rows():
    # Plain rows are pushed TO gcal, never sourced FROM it -- pruning them
    # on a calendar mismatch would delete user-authored deadlines.
    text, removed = dl.prune_deleted(MD, [], dl.DEFAULT_KEYWORDS,
                                      window_start="2099-07-01", window_end="2099-12-31")
    assert removed == ["2099-07-16 — MPU — Reflection submission"]
    assert "- 2099-08-01 — CS101 — Assignment 1" in text


# ── sync_with_calendar ───────────────────────────────────────────────────────

def test_sync_with_calendar_adds_and_prunes_in_one_pass(tmp_path, monkeypatch):
    from datetime import date, timedelta, timezone
    from voice import config as cfg

    today = date.today()
    stale_date = (today - timedelta(days=1)).isoformat()
    new_date = (today + timedelta(days=5)).isoformat()

    md = (
        "# DEADLINES\n\n## Active\n\n"
        f"- nogcal: {stale_date} — Personal — Old thing due\n"
    )
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "DEADLINES.md").write_text(md, encoding="utf-8")
    monkeypatch.setattr(cfg, "get_vault_dir", lambda: vault)
    monkeypatch.setattr(cfg, "get_timezone", lambda: timezone.utc)

    # The stale row's source event is absent from this fetch (deleted from
    # Google Calendar), so it's pruned in the same pass a new event is added.
    added, removed = dl.sync_with_calendar(
        [_ev("Rent due", new_date)], dl.DEFAULT_KEYWORDS,
        days_back=3, days_forward=30,
    )
    assert added == [f"{new_date} — Rent due"]
    assert removed == [f"{stale_date} — Personal — Old thing due"]
    text = (vault / "DEADLINES.md").read_text(encoding="utf-8")
    assert "Rent due" in text
    assert "Old thing due" not in text
