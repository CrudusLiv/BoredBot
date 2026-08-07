"""Tests for heartbeat vault state writer."""
from __future__ import annotations
import json
import sys
from datetime import datetime
from pathlib import Path
import pytest

# Add .claude/scripts/ to path (same pattern as other tests in this repo)
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / ".claude" / "scripts"))

# Snapshot fixtures reused across tests
SNAP_FULL = {
    "timestamp": 1747656000.0,
    "github": {"push_count": 3, "items": []},
    "inbox": {"count": 0, "files": []},
}

SNAP_ERROR = {
    "timestamp": 1747656000.0,
    "github": {"error": "no token"},
}


def test_write_github_counts(tmp_vault):
    from core import vault_state_writer
    vault_state_writer.write_github(SNAP_FULL)

    out = tmp_vault / "state" / "github-counts.md"
    assert out.exists()
    assert "prs_open: 3" in out.read_text(encoding="utf-8")


def test_write_github_skips_on_error(tmp_vault):
    from core import vault_state_writer
    vault_state_writer.write_github(SNAP_ERROR)

    assert not (tmp_vault / "state" / "github-counts.md").exists()


def test_write_heartbeat_state_always_writes(tmp_vault):
    from core import vault_state_writer
    vault_state_writer.write_heartbeat_state(SNAP_ERROR)

    out = tmp_vault / "state" / "heartbeat-state.json"
    assert out.exists()
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["timestamp"] == SNAP_ERROR["timestamp"]


def test_write_all_creates_all_files(tmp_vault):
    from core import vault_state_writer
    vault_state_writer.write_all(SNAP_FULL)

    state = tmp_vault / "state"
    assert (state / "github-counts.md").exists()
    assert (state / "heartbeat-state.json").exists()


# ── write_gcal_today ──────────────────────────────────────────────────────────

def _today_kl_str() -> str:
    from datetime import timezone, timedelta
    kl = timezone(timedelta(hours=8))
    return datetime.now(tz=kl).strftime("%Y-%m-%d")

def _yesterday_kl_str() -> str:
    from datetime import timezone, timedelta
    kl = timezone(timedelta(hours=8))
    return (datetime.now(tz=kl) - timedelta(days=1)).strftime("%Y-%m-%d")


def test_write_gcal_today_filters_to_today(tmp_vault):
    from core import vault_state_writer
    today = _today_kl_str()
    yesterday = _yesterday_kl_str()
    snap = {"gcal": {"events": [
        {"start": f"{today}T09:00:00+08:00",     "summary": "Morning standup"},
        {"start": f"{yesterday}T18:00:00+08:00", "summary": "Yesterday's event"},
        {"start": f"{today}T14:30:00+08:00",     "summary": "Afternoon review"},
    ]}}
    vault_state_writer.write_gcal_today(snap)

    out = tmp_vault / "state" / "gcal-today.md"
    assert out.exists()
    text = out.read_text(encoding="utf-8")
    assert "Morning standup" in text
    assert "Afternoon review" in text
    assert "Yesterday" not in text


def test_write_gcal_today_skips_on_error(tmp_vault):
    from core import vault_state_writer
    vault_state_writer.write_gcal_today({"gcal": {"error": "oauth not configured"}})
    assert not (tmp_vault / "state" / "gcal-today.md").exists()


def test_write_gcal_today_skips_when_no_events(tmp_vault):
    from core import vault_state_writer
    vault_state_writer.write_gcal_today({"gcal": {}})
    assert not (tmp_vault / "state" / "gcal-today.md").exists()


def test_write_all_creates_gcal_today(tmp_vault):
    from core import vault_state_writer
    today = _today_kl_str()
    snap = {**SNAP_FULL, "gcal": {"events": [
        {"start": f"{today}T10:00:00+08:00", "summary": "Test event"}
    ]}}
    vault_state_writer.write_all(snap)
    assert (tmp_vault / "state" / "gcal-today.md").exists()
