"""activate_profile tool — activates a named app-launch profile (voice.profiles)."""
from __future__ import annotations

import json


def activate_profile(name: str) -> str:
    from voice import profiles
    return json.dumps(profiles.activate(name))
