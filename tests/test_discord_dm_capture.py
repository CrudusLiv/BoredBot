"""Tests for discord_dm_capture.py — classify + route self-DMs."""
from __future__ import annotations

import importlib
import sqlite3
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".claude" / "scripts"))


def _make_db(path: Path, messages: list[dict]) -> Path:
    db = path / "discord_cache.db"
    conn = sqlite3.connect(str(db))
    conn.execute("""
        CREATE TABLE messages (
            id TEXT PRIMARY KEY,
            channel_id TEXT,
            content TEXT,
            author_id TEXT,
            author_name TEXT,
            created_at REAL,
            is_dm INTEGER DEFAULT 0,
            is_self INTEGER DEFAULT 0,
            is_bot INTEGER DEFAULT 0
        )
    """)
    for m in messages:
        conn.execute(
            "INSERT INTO messages VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                m["id"], m.get("channel_id", "ch1"), m.get("content", ""),
                m.get("author_id", "u1"), m.get("author_name", "user"),
                m.get("created_at", time.time()),
                m.get("is_dm", 0), m.get("is_self", 0), m.get("is_bot", 0),
            ),
        )
    conn.commit()
    conn.close()
    return db


# ──────────────────────── classify_rule_based ─────────────────────────────────

class TestClassifyRuleBased:
    @pytest.fixture(autouse=True)
    def _import(self):
        from core import discord_dm_capture as mod
        self.classify = mod.classify_rule_based

    def test_empty_is_chitchat(self):
        assert self.classify("") == "chit-chat"

    def test_plain_message_is_chitchat(self):
        assert self.classify("hey what's up") == "chit-chat"

    def test_dollar_symbol_is_finance(self):
        assert self.classify("$50 for coffee") == "finance"

    def test_rm_prefix_is_finance(self):
        assert self.classify("rm 25 on lunch") == "finance"

    def test_myr_prefix_is_finance(self):
        assert self.classify("myr100 groceries") == "finance"

    def test_usd_prefix_is_finance(self):
        assert self.classify("USD 12 for a book") == "finance"

    def test_finance_keyword_spent(self):
        assert self.classify("spent 20 on transport today") == "finance"

    def test_finance_keyword_paid(self):
        assert self.classify("paid my internet bill") == "finance"

    def test_finance_keyword_earned(self):
        assert self.classify("earned some freelance money") == "finance"

    def test_note_colon_prefix(self):
        assert self.classify("note: check lecture 3 slides") == "note"

    def test_note_dash_prefix(self):
        assert self.classify("note - remember to submit") == "note"

    def test_note_to_self_prefix(self):
        assert self.classify("note to self: call mum tomorrow") == "note"

    def test_note_prefix_with_nothing_after_is_chitchat(self):
        assert self.classify("note:   ") == "chit-chat"

    def test_question_is_chitchat(self):
        assert self.classify("what time does the lecture start?") == "chit-chat"


# ──────────────────────────── route ───────────────────────────────────────────

class TestRoute:
    def test_chitchat_discarded(self, tmp_vault, monkeypatch):
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_vault.parent.parent))
        from core import discord_dm_capture as mod
        importlib.reload(mod)
        label = mod.route({"id": "1", "content": "hey", "created_at": time.time()})
        assert label == "chit-chat"

    def test_finance_creates_file(self, tmp_vault, monkeypatch):
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_vault.parent.parent))
        from core import discord_dm_capture as mod
        importlib.reload(mod)
        label = mod.route({"id": "2", "content": "spent rm15 on coffee", "created_at": time.time()})
        assert label == "finance"
        from datetime import datetime, timedelta, timezone
        KL = timezone(timedelta(hours=8))
        dt = datetime.fromtimestamp(time.time(), tz=KL)
        assert (tmp_vault / "finance" / f"{dt.strftime('%Y-%m')}.md").exists()

    def test_note_written_to_notes_md(self, tmp_vault, monkeypatch):
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_vault.parent.parent))
        from core import discord_dm_capture as mod
        importlib.reload(mod)
        label = mod.route({"id": "3", "content": "note: check assignment spec", "created_at": time.time()})
        assert label == "note"
        notes_file = tmp_vault / "notes" / "NOTES.md"
        assert notes_file.exists()
        assert "check assignment spec" in notes_file.read_text(encoding="utf-8")


# ──────────────────────────── scan_and_route ──────────────────────────────────

class TestScanAndRoute:
    def test_missing_db_returns_zeros(self, tmp_vault, tmp_data, monkeypatch):
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_vault.parent.parent))
        from core import discord_dm_capture as mod
        importlib.reload(mod)
        counts = mod.scan_and_route(
            tmp_data / "noexist.db",
            user_id="123",
            state_path=tmp_data / "state.json",
        )
        assert counts == {"note": 0, "finance": 0, "chit-chat": 0}

    def test_routes_self_dm_note(self, tmp_vault, tmp_data, monkeypatch):
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_vault.parent.parent))
        from core import discord_dm_capture as mod
        importlib.reload(mod)
        db = _make_db(tmp_data, [
            {"id": "n1", "content": "note: study chapter 5", "created_at": time.time(),
             "is_dm": 1, "is_self": 1},
        ])
        counts = mod.scan_and_route(db, user_id="u1", state_path=tmp_data / "state.json")
        assert counts["note"] == 1

    def test_routes_self_dm_finance(self, tmp_vault, tmp_data, monkeypatch):
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_vault.parent.parent))
        from core import discord_dm_capture as mod
        importlib.reload(mod)
        db = _make_db(tmp_data, [
            {"id": "f1", "content": "spent rm40 on textbook", "created_at": time.time(),
             "is_dm": 1, "is_self": 1},
        ])
        counts = mod.scan_and_route(db, user_id="u1", state_path=tmp_data / "state.json")
        assert counts["finance"] == 1

    def test_non_dm_ignored(self, tmp_vault, tmp_data, monkeypatch):
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_vault.parent.parent))
        from core import discord_dm_capture as mod
        importlib.reload(mod)
        db = _make_db(tmp_data, [
            {"id": "nd1", "content": "note: server message", "created_at": time.time(),
             "is_dm": 0, "is_self": 1},
        ])
        counts = mod.scan_and_route(db, user_id="u1", state_path=tmp_data / "state.json")
        assert counts["note"] == 0

    def test_already_seen_skipped(self, tmp_vault, tmp_data, monkeypatch):
        import json
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_vault.parent.parent))
        from core import discord_dm_capture as mod
        importlib.reload(mod)
        db = _make_db(tmp_data, [
            {"id": "seen1", "content": "note: old note", "created_at": time.time(),
             "is_dm": 1, "is_self": 1},
        ])
        sp = tmp_data / "state.json"
        sp.write_text(
            json.dumps({"seen_message_ids": [{"id": "seen1", "t": time.time()}]}),
            encoding="utf-8",
        )
        counts = mod.scan_and_route(db, user_id="u1", state_path=sp)
        assert counts["note"] == 0

    def test_old_messages_outside_ttl_ignored(self, tmp_vault, tmp_data, monkeypatch):
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_vault.parent.parent))
        from core import discord_dm_capture as mod
        importlib.reload(mod)
        old_ts = time.time() - 25 * 3600
        db = _make_db(tmp_data, [
            {"id": "old1", "content": "note: ancient note", "created_at": old_ts,
             "is_dm": 1, "is_self": 1},
        ])
        counts = mod.scan_and_route(db, user_id="u1", state_path=tmp_data / "state.json",
                                    now=time.time())
        assert counts["note"] == 0

    def test_bot_dm_channel_id_restricts_scan(self, tmp_vault, tmp_data, monkeypatch):
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_vault.parent.parent))
        from core import discord_dm_capture as mod
        importlib.reload(mod)
        db = _make_db(tmp_data, [
            {"id": "c1", "channel_id": "ch_target", "content": "note: right channel",
             "created_at": time.time(), "is_dm": 1, "is_self": 1},
            {"id": "c2", "channel_id": "ch_other", "content": "note: wrong channel",
             "created_at": time.time(), "is_dm": 1, "is_self": 1},
        ])
        counts = mod.scan_and_route(
            db, user_id="u1", state_path=tmp_data / "state.json",
            bot_dm_channel_id="ch_target",
        )
        assert counts["note"] == 1
