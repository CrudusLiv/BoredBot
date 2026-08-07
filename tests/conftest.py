"""Shared fixtures for second-brain plan tests."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import Mock

import pytest


@pytest.fixture(autouse=True)
def _evict_leaked_mock_modules():
    """Drop any Mock that a test left behind in sys.modules.

    Several test files stub heavy imports with MagicMock (swapping in fakes,
    or reloading a module under test). If such a stub leaks it poisons every
    later test file that imports the real module -- the symptom is a downstream
    test getting a MagicMock where it expected real behaviour.

    We only evict Mock instances, never real modules: popping a real submodule
    while its parent package still holds the attribute breaks `from pkg import
    sub` + importlib.reload. Real re-imports are harmless to leave cached.

    NOTE: this only covers mutations made while a test *runs*. Files that stub
    sys.modules at import time (top-of-module, during collection) must still
    clean up after their own import -- see tests/test_heartbeat_gating.py."""
    snapshot = set(sys.modules)
    yield
    for name in set(sys.modules) - snapshot:
        if isinstance(sys.modules.get(name), Mock):
            sys.modules.pop(name, None)


@pytest.fixture
def tmp_vault(tmp_path: Path, monkeypatch) -> Path:
    """Materialise a minimal vault under tmp_path and point modules at it.

    Modules under .claude/scripts/ derive VAULT from CLAUDE_PROJECT_DIR,
    so setting that env var redirects them at the temp tree."""
    vault = tmp_path / "Dynamous" / "Memory"
    (vault / "daily").mkdir(parents=True)
    (vault / "lectures").mkdir(parents=True)
    (vault / "projects").mkdir(parents=True)
    (vault / "finance").mkdir(parents=True)
    (vault / "inbox" / "_processed").mkdir(parents=True)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    return vault


@pytest.fixture
def tmp_data(tmp_path: Path, monkeypatch) -> Path:
    """Provide an isolated .claude/data/ for state files."""
    data = tmp_path / ".claude" / "data"
    data.mkdir(parents=True)
    return data
