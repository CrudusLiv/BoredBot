"""Tests for voice_notices.jsonl growth capping in voice/heartbeat.py.

_post() appends one JSON line per notice; _trim_notices() rewrites the file
to the newest _NOTICES_KEEP_LINES lines once it exceeds _NOTICES_MAX_BYTES."""
from __future__ import annotations

import json

import pytest

from voice import config as cfg
from voice import heartbeat as hb_mod


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Isolated data dir pointing the notices file into tmp_path."""
    monkeypatch.setattr(cfg, "get_data_dir", lambda: tmp_path)
    return tmp_path / "voice_notices.jsonl"


def _fill(path, n_lines, line_bytes=600):
    """Write n_lines of valid JSONL, each padded to ~line_bytes."""
    pad = "x" * line_bytes
    with path.open("w", encoding="utf-8") as fh:
        for i in range(n_lines):
            fh.write(json.dumps({"id": f"{i:012d}", "text": pad, "read": False}) + "\n")


def test_below_size_threshold_untouched(env):
    _fill(env, 10)
    before = env.read_text(encoding="utf-8")
    hb_mod._trim_notices(env)
    assert env.read_text(encoding="utf-8") == before


def test_oversize_file_trimmed_to_keep_lines(env):
    n = hb_mod._NOTICES_KEEP_LINES + 100
    _fill(env, n)  # 600 B/line * 600 lines >> 256 KB
    assert env.stat().st_size > hb_mod._NOTICES_MAX_BYTES
    hb_mod._trim_notices(env)
    lines = env.read_text(encoding="utf-8").splitlines()
    assert len(lines) == hb_mod._NOTICES_KEEP_LINES
    # newest lines survive, in order, still valid JSON
    assert json.loads(lines[-1])["id"] == f"{n - 1:012d}"
    assert json.loads(lines[0])["id"] == f"{n - hb_mod._NOTICES_KEEP_LINES:012d}"


def test_missing_file_is_noop(env):
    hb_mod._trim_notices(env)  # must not raise
    assert not env.exists()


def test_post_appends_and_stays_valid_jsonl(env, monkeypatch):
    monkeypatch.setattr(cfg, "load", lambda: {"timezone_offset_hours": 8})
    hb_mod._post("hello from the test")
    lines = env.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["text"] == "hello from the test"
    assert entry["read"] is False
