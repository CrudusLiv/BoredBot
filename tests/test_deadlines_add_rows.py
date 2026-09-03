"""voice.deadlines.add_rows — merge non-calendar deadline pairs into DEADLINES.md."""
from __future__ import annotations

from voice import deadlines


def _vault(tmp_path, monkeypatch, body="# Deadlines\n\n## Active\n\n## Done\n"):
    p = tmp_path / "DEADLINES.md"
    p.write_text(body, encoding="utf-8")
    monkeypatch.setattr(deadlines, "_path", lambda: p)
    return p


def test_adds_new_rows(tmp_path, monkeypatch):
    p = _vault(tmp_path, monkeypatch)
    added = deadlines.add_rows([("2026-10-15", "BIT216 — Brief")])
    assert added == ["2026-10-15 — BIT216 — Brief"]
    assert "- nogcal: 2026-10-15 — BIT216 — Brief" in p.read_text(encoding="utf-8")


def test_dedupes_against_existing(tmp_path, monkeypatch):
    _vault(tmp_path, monkeypatch,
           "## Active\n\n- nogcal: 2026-10-15 — BIT216 — Brief\n\n## Done\n")
    assert deadlines.add_rows([("2026-10-15", "BIT216 — Brief")]) == []


def test_empty_pairs_noop(tmp_path, monkeypatch):
    _vault(tmp_path, monkeypatch)
    assert deadlines.add_rows([]) == []


def test_no_vault_noop(monkeypatch):
    monkeypatch.setattr(deadlines, "_path", lambda: None)
    assert deadlines.add_rows([("2026-10-15", "x")]) == []
