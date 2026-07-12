"""voice/heartbeat.py::_fetch_deadlines — only real deadline rows, not prose."""
from __future__ import annotations

from voice import config as cfg
from voice import heartbeat as hb_mod

DEADLINES_MD = """# DEADLINES

> Loaded into every session.

## Format

`YYYY-MM-DD — <course/project> — <title>` — one per line under the heading below.

To push a row to Google Calendar, leave it as-is. To opt out, prefix with `nogcal:`.

## Active

- 2099-01-01 — CS101 — Assignment 1
- nogcal: 2099-02-02 — DIP209 — Capstone draft
Some stray prose that is not a deadline.
"""


def _vault(tmp_path, monkeypatch, text=DEADLINES_MD):
    (tmp_path / "DEADLINES.md").write_text(text, encoding="utf-8")
    monkeypatch.setattr(cfg, "get_vault_dir", lambda: tmp_path)


def test_returns_only_dated_rows(tmp_path, monkeypatch):
    _vault(tmp_path, monkeypatch)
    lines = hb_mod._fetch_deadlines()
    assert lines == [
        "- 2099-01-01 — CS101 — Assignment 1",
        "- nogcal: 2099-02-02 — DIP209 — Capstone draft",
    ]


def test_instructions_only_file_yields_nothing(tmp_path, monkeypatch):
    text = DEADLINES_MD.split("## Active")[0] + "## Active\n"
    _vault(tmp_path, monkeypatch, text)
    assert hb_mod._fetch_deadlines() == []


def test_no_vault_returns_empty(monkeypatch):
    monkeypatch.setattr(cfg, "get_vault_dir", lambda: None)
    assert hb_mod._fetch_deadlines() == []
