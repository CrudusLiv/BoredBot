"""Smoke test for query.py's DISPATCH table -- confirms outlook is wired in."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".claude" / "scripts"))
sys.path.insert(0, str(ROOT / ".claude" / "scripts" / "integrations"))


def test_outlook_registered_in_dispatch():
    import importlib
    import query as q
    importlib.reload(q)
    assert "outlook" in q.DISPATCH


def test_outlook_registered_in_registry_status():
    import importlib
    import integrations.registry as registry
    importlib.reload(registry)
    names = [i.name for i in registry.INTEGRATIONS]
    assert "outlook" in names
