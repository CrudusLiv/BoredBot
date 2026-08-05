"""query.py gcal sync -- new CLI subcommand over core.gcal_sync.run()."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / ".claude" / "scripts"))
from integrations import gcal_int  # noqa: E402
from core import gcal_sync  # noqa: E402


def test_sync_prints_created_count(monkeypatch, capsys):
    monkeypatch.setattr(gcal_sync, "run", lambda: 3)

    rc = gcal_int.handle_query(["sync", "--json"])

    assert rc == 0
    assert json.loads(capsys.readouterr().out) == {"created": 3}


def test_sync_zero_created(monkeypatch, capsys):
    monkeypatch.setattr(gcal_sync, "run", lambda: 0)

    gcal_int.handle_query(["sync", "--json"])

    assert json.loads(capsys.readouterr().out) == {"created": 0}
