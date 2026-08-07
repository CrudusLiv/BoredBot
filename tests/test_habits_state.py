"""Tests for habits_state: JSON streak + history tracking."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".claude" / "scripts"))

from core import habits_state

PILLARS = ("Lecture engagement", "Project progress", "Research / learning", "Personal goals")


@pytest.fixture
def state_file(tmp_path, monkeypatch):
    """Redirect STATE_FILE to a temp location and reset module state between tests."""
    sf = tmp_path / "habits_state.json"
    monkeypatch.setattr(habits_state, "STATE_FILE", sf)
    yield sf


def test_record_and_streak(state_file):
    for p in PILLARS:
        habits_state.record_completion("2026-06-10", p)
    state = habits_state.load_state()
    assert all(state["history"]["2026-06-10"][p] for p in PILLARS)
    assert state["current_streak"] >= 1


def test_streak_increments_on_consecutive_days(state_file):
    for d in ("2026-06-10", "2026-06-11", "2026-06-12"):
        habits_state.record_completion(d, "Lecture engagement")
    state = habits_state.load_state()
    streak = habits_state.compute_streak(state["history"], "2026-06-12")
    assert streak == 3


def test_streak_resets_on_gap(state_file):
    for d in ("2026-06-10", "2026-06-12"):  # gap on 11th
        habits_state.record_completion(d, "Lecture engagement")
    state = habits_state.load_state()
    streak = habits_state.compute_streak(state["history"], "2026-06-12")
    assert streak == 1


def test_weekly_summary(state_file):
    for p in PILLARS:
        habits_state.record_completion("2026-06-09", p)
    summary = habits_state.get_weekly_summary(habits_state.load_state()["history"], "2026-06-09", total=len(PILLARS))
    day = next(d for d in summary if d["date"] == "2026-06-09")
    assert day["pct"] == 100


def test_best_streak_preserved(state_file):
    for d in ("2026-06-01", "2026-06-02", "2026-06-03", "2026-06-04", "2026-06-05"):
        habits_state.record_completion(d, "Lecture engagement")
    for d in ("2026-06-08", "2026-06-09"):
        habits_state.record_completion(d, "Lecture engagement")
    state = habits_state.load_state()
    assert state["best_streak"] == 5
    assert state["current_streak"] == 2
