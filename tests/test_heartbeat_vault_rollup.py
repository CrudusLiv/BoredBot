"""voice/heartbeat.py::_check_vault_daily_rollup — once-daily append of
voice highlights + heartbeat digest + finance summary to the vault's
Dynamous/Memory/daily/ note."""
from __future__ import annotations

import json
from datetime import date, datetime, timezone, timedelta

from voice import config as cfg
from voice import heartbeat as hb_mod
from voice.heartbeat import Heartbeat

CONF = {
    "timezone_offset_hours": 8, "vault_rollup_enabled": True,
    "vault_rollup_time": "23:30",
}


def _env(tmp_path, monkeypatch, conf=None, hour=23, minute=35):
    monkeypatch.setattr(cfg, "get_data_dir", lambda: tmp_path)
    monkeypatch.setattr(cfg, "load", lambda: dict(conf or CONF))
    fixed_now = datetime(2026, 7, 7, hour, minute, tzinfo=timezone(timedelta(hours=8)))
    monkeypatch.setattr(hb_mod, "datetime", type("F", (), {"now": staticmethod(lambda tz=None: fixed_now)}))
    blocks = []
    monkeypatch.setattr(hb_mod.vault_daily, "append_block", lambda label, content: blocks.append((label, content)))
    monkeypatch.setattr(hb_mod.finance_tracker, "day_summary", lambda when=None: "")
    monkeypatch.setattr(hb_mod.core_llm, "is_available", lambda: False)
    return blocks


def test_disabled_skips(tmp_path, monkeypatch):
    blocks = _env(tmp_path, monkeypatch, dict(CONF, vault_rollup_enabled=False))
    hb = Heartbeat(interval_minutes=30, idle_fn=lambda: None)
    hb._check_vault_daily_rollup()
    assert blocks == []


def test_before_scheduled_time_does_nothing(tmp_path, monkeypatch):
    blocks = _env(tmp_path, monkeypatch, hour=20, minute=0)
    hb = Heartbeat(interval_minutes=30, idle_fn=lambda: None)
    hb._check_vault_daily_rollup()
    assert blocks == []


def test_only_fires_once_per_day(tmp_path, monkeypatch):
    blocks = _env(tmp_path, monkeypatch)
    hb = Heartbeat(interval_minutes=30, idle_fn=lambda: None)
    hb._vault_rollup_done_date = date(2026, 7, 7)
    hb._check_vault_daily_rollup()
    assert blocks == []


def test_no_sections_writes_nothing(tmp_path, monkeypatch):
    blocks = _env(tmp_path, monkeypatch)
    hb = Heartbeat(interval_minutes=30, idle_fn=lambda: None)
    hb._check_vault_daily_rollup()
    assert blocks == []
    assert hb._vault_rollup_done_date == date(2026, 7, 7)


def test_finance_section_appended(tmp_path, monkeypatch):
    blocks = _env(tmp_path, monkeypatch)
    monkeypatch.setattr(hb_mod.finance_tracker, "day_summary", lambda when=None: "RM50.00 spent today")
    hb = Heartbeat(interval_minutes=30, idle_fn=lambda: None)
    hb._check_vault_daily_rollup()
    assert ("Finance", "RM50.00 spent today") in blocks


def test_heartbeat_digest_section_filters_to_today(tmp_path, monkeypatch):
    blocks = _env(tmp_path, monkeypatch)
    notices = tmp_path / "voice_notices.jsonl"
    notices.write_text(
        json.dumps({"ts": "2026-07-06T09:00:00+08:00", "text": "yesterday's notice"}) + "\n"
        + json.dumps({"ts": "2026-07-07T10:15:00+08:00", "text": "GitHub: new PR"}) + "\n",
        encoding="utf-8",
    )
    hb = Heartbeat(interval_minutes=30, idle_fn=lambda: None)
    hb._check_vault_daily_rollup()
    assert len(blocks) == 1
    label, content = blocks[0]
    assert label == "Heartbeat digest"
    assert "GitHub: new PR" in content
    assert "yesterday's notice" not in content


def test_voice_section_skipped_when_no_brain(tmp_path, monkeypatch):
    blocks = _env(tmp_path, monkeypatch)
    hb = Heartbeat(interval_minutes=30, idle_fn=lambda: None)
    assert hb._brain is None
    hb._check_vault_daily_rollup()
    assert blocks == []


def test_voice_section_skipped_when_llm_unavailable(tmp_path, monkeypatch):
    blocks = _env(tmp_path, monkeypatch)

    class _FakeBrain:
        history = [{"role": "user", "content": "what's on my calendar"}]

    hb = Heartbeat(interval_minutes=30, idle_fn=lambda: None, brain=_FakeBrain())
    hb._check_vault_daily_rollup()
    assert blocks == []


def test_voice_section_appended_when_distilled(tmp_path, monkeypatch):
    blocks = _env(tmp_path, monkeypatch)
    monkeypatch.setattr(hb_mod.core_llm, "is_available", lambda: True)
    monkeypatch.setattr(hb_mod.core_llm, "call", lambda *a, **kw: "### Facts\n- likes RM50 lunches")

    class _FakeBrain:
        history = [{"role": "user", "content": "log 50 food lunch"}]

    hb = Heartbeat(interval_minutes=30, idle_fn=lambda: None, brain=_FakeBrain())
    hb._check_vault_daily_rollup()
    assert ("Voice conversation", "### Facts\n- likes RM50 lunches") in blocks


def test_voice_section_skipped_on_no_durable_items(tmp_path, monkeypatch):
    blocks = _env(tmp_path, monkeypatch)
    monkeypatch.setattr(hb_mod.core_llm, "is_available", lambda: True)
    monkeypatch.setattr(hb_mod.core_llm, "call", lambda *a, **kw: "_(no durable items)_")

    class _FakeBrain:
        history = [{"role": "user", "content": "hi"}]

    hb = Heartbeat(interval_minutes=30, idle_fn=lambda: None, brain=_FakeBrain())
    hb._check_vault_daily_rollup()
    assert blocks == []
