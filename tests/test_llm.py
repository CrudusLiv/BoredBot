"""Tests for llm.py — config loading and dispatcher."""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

repo_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repo_root / ".claude" / "scripts"))


def _reload():
    import core.llm as m
    importlib.reload(m)
    m._config_cache = None
    return m


# --- Config loader ---

def test_config_missing_file_returns_defaults(tmp_path, monkeypatch):
    m = _reload()
    monkeypatch.setattr(m, "_CONFIG_PATH", tmp_path / "nonexistent.json")
    m._config_cache = None
    cfg = m._load_config()
    assert cfg["default_backend"] == "claude"
    assert cfg["routing"] == {}


def test_config_malformed_json_returns_defaults(tmp_path, monkeypatch):
    bad = tmp_path / "llm-config.json"
    bad.write_text("not json")
    m = _reload()
    monkeypatch.setattr(m, "_CONFIG_PATH", bad)
    m._config_cache = None
    cfg = m._load_config()
    assert cfg["default_backend"] == "claude"


def test_config_valid_json_merged_with_defaults(tmp_path, monkeypatch):
    cfg_file = tmp_path / "llm-config.json"
    cfg_file.write_text(json.dumps({
        "routing": {"inbox_classify": {"backend": "claude", "model": "haiku"}},
    }))
    m = _reload()
    monkeypatch.setattr(m, "_CONFIG_PATH", cfg_file)
    m._config_cache = None
    cfg = m._load_config()
    assert cfg["default_backend"] == "claude"
    assert cfg["routing"]["inbox_classify"]["backend"] == "claude"
    assert "claude" in cfg["backends"]  # preserved from defaults


def test_config_cached_after_first_load(tmp_path, monkeypatch):
    cfg_file = tmp_path / "llm-config.json"
    cfg_file.write_text(json.dumps({"default_backend": "claude"}))
    m = _reload()
    monkeypatch.setattr(m, "_CONFIG_PATH", cfg_file)
    m._config_cache = None
    first = m._load_config()
    cfg_file.write_text(json.dumps({"default_backend": "claude"}))
    second = m._load_config()
    assert first is second  # cache hit — file change ignored


# --- Dispatcher ---

def test_force_backend_env_overrides_routing(monkeypatch):
    m = _reload()
    m._config_cache = {
        "default_backend": "claude",
        "fallback_backend": None,
        "backends": {},
        "routing": {"inbox_classify": {"backend": "claude", "model": "haiku"}},
    }
    monkeypatch.setenv("LLM_FORCE_BACKEND", "claude")
    backend, model = m._resolve_backend("inbox_classify")
    assert backend == "claude"
    assert model is None


def test_task_in_routing_table_uses_configured_backend(monkeypatch):
    m = _reload()
    m._config_cache = {
        "default_backend": "claude",
        "fallback_backend": None,
        "backends": {},
        "routing": {"inbox_classify": {"backend": "claude", "model": "haiku"}},
    }
    monkeypatch.delenv("LLM_FORCE_BACKEND", raising=False)
    backend, model = m._resolve_backend("inbox_classify")
    assert backend == "claude"
    assert model == "haiku"


def test_unknown_task_uses_default_backend(monkeypatch):
    m = _reload()
    m._config_cache = {
        "default_backend": "claude",
        "fallback_backend": None,
        "backends": {},
        "routing": {},
    }
    monkeypatch.delenv("LLM_FORCE_BACKEND", raising=False)
    backend, model = m._resolve_backend("nonexistent_task")
    assert backend == "claude"
    assert model is None


def test_no_task_uses_default_backend(monkeypatch):
    m = _reload()
    m._config_cache = {
        "default_backend": "claude",
        "fallback_backend": None,
        "backends": {},
        "routing": {},
    }
    monkeypatch.delenv("LLM_FORCE_BACKEND", raising=False)
    backend, model = m._resolve_backend(None)
    assert backend == "claude"
    assert model is None


def test_call_routes_task_to_claude(monkeypatch):
    m = _reload()
    m._config_cache = {
        "default_backend": "claude",
        "fallback_backend": None,
        "backends": {"claude": {}},
        "routing": {"inbox_classify": {"backend": "claude", "model": "haiku"}},
    }
    monkeypatch.delenv("LLM_FORCE_BACKEND", raising=False)

    with patch.object(m, "_call_claude", return_value="classified") as mock_claude:
        result = m.call("classify this", task="inbox_classify")

    mock_claude.assert_called_once()
    assert result == "classified"


def test_call_no_task_uses_claude_by_default(monkeypatch):
    m = _reload()
    m._config_cache = {
        "default_backend": "claude",
        "fallback_backend": None,
        "backends": {},
        "routing": {},
    }
    monkeypatch.delenv("LLM_FORCE_BACKEND", raising=False)

    with patch.object(m, "_call_claude", return_value="answer") as mock_claude:
        result = m.call("question")

    mock_claude.assert_called_once()
    assert result == "answer"
