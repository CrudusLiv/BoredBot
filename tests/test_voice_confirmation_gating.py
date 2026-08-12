"""voice/config.json's requires_confirmation list must cover every tool
whose own docstring says "Requires user confirmation" -- a gap here means
a destructive tool silently skips its confirm gate, as
create_calendar_event and complete_deadline did before this fix."""
from __future__ import annotations

import json
from pathlib import Path


def test_calendar_and_deadline_tools_are_gated():
    config_path = Path(__file__).resolve().parents[1] / "voice" / "config.json"
    conf = json.loads(config_path.read_text(encoding="utf-8"))
    gated = set(conf["requires_confirmation"])
    for name in (
        "create_calendar_event", "complete_deadline",
        "delete_calendar_event", "create_reminder",
    ):
        assert name in gated, f"{name!r} is not in requires_confirmation"
