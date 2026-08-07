"""Tests for vault/transactions.py — JSONL log + last-entry helpers."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".claude" / "scripts"))

from vault import transactions  # noqa: E402


def _log_for(tmp_path: Path) -> Path:
    """Where transactions._log_path() will write when CLAUDE_PROJECT_DIR=tmp_path."""
    return tmp_path / ".claude" / "data" / "vault_transactions.jsonl"


def test_append_creates_log_file_if_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    log = _log_for(tmp_path)
    transactions.append({"action": "append", "args": {"path": "x.md"}, "undo_state": {"original_length": 0}})
    assert log.exists()
    lines = log.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    parsed = json.loads(lines[0])
    assert parsed["action"] == "append"
    assert "ts" in parsed  # auto-stamped


def test_append_appends_without_clobbering(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    log = _log_for(tmp_path)
    transactions.append({"action": "a", "args": {}, "undo_state": {}})
    transactions.append({"action": "b", "args": {}, "undo_state": {}})
    lines = log.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["action"] == "a"
    assert json.loads(lines[1])["action"] == "b"


def test_read_last_returns_most_recent(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    transactions.append({"action": "a", "args": {}, "undo_state": {}})
    transactions.append({"action": "b", "args": {}, "undo_state": {}})
    last = transactions.read_last()
    assert last["action"] == "b"


def test_read_last_returns_none_when_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    assert transactions.read_last() is None
