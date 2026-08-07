"""update_profile_app_state tool — set per-app cwd/args on an existing profile."""
from __future__ import annotations

import json


def update_profile_app_state(profile: str, alias: str, cwd: str = "") -> str:
    from voice import profiles

    try:
        profiles.set_app_state(profile, alias, cwd=cwd or None)
    except KeyError as exc:
        return json.dumps({"error": str(exc)})
    return json.dumps({"status": "ok"})
