"""voice/config.json (checked-in dev config) must not override DEFAULTS'
tts_engine back to a stale value -- regression pin for the elevenlabs bug."""
from __future__ import annotations

import json
from pathlib import Path


def test_dev_config_tts_engine_is_chatterbox():
    config_path = Path(__file__).resolve().parents[1] / "voice" / "config.json"
    data = json.loads(config_path.read_text(encoding="utf-8"))
    assert data.get("tts_engine") == "chatterbox"
