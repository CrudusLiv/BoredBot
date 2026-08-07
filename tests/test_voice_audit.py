"""Tests for voice/audit.py::log — append-only JSONL audit entries, including
the optional structured `meta` field used by STT instrumentation."""
from __future__ import annotations

import json

import pytest

from voice import config as cfg
from voice import audit


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "get_data_dir", lambda: tmp_path)
    return tmp_path / "voice_audit.jsonl"


def test_log_without_meta_omits_meta_key(env):
    audit.log("user", "hello")
    entry = json.loads(env.read_text(encoding="utf-8").splitlines()[0])
    assert "meta" not in entry


def test_log_with_meta_includes_meta_dict(env):
    audit.log("stt", "hello there", meta={
        "duration_s": 1.5, "word_count": 2, "words_per_second": 1.33,
    })
    entry = json.loads(env.read_text(encoding="utf-8").splitlines()[0])
    assert entry["role"] == "stt"
    assert entry["content"] == "hello there"
    assert entry["meta"] == {"duration_s": 1.5, "word_count": 2, "words_per_second": 1.33}


def test_log_with_empty_meta_dict_omits_meta_key(env):
    audit.log("user", "hello", meta={})
    entry = json.loads(env.read_text(encoding="utf-8").splitlines()[0])
    assert "meta" not in entry


def test_log_meta_coexists_with_tool_name_and_outcome(env):
    audit.log("tool", "did a thing", tool_name="search_vault", outcome="user", meta={"k": "v"})
    entry = json.loads(env.read_text(encoding="utf-8").splitlines()[0])
    assert entry["tool"] == "search_vault"
    assert entry["outcome"] == "user"
    assert entry["meta"] == {"k": "v"}
