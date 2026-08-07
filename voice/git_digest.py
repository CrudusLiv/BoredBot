"""Local git-log reader for the daily commit summary — deliberately reads
the working tree's own history via `git log`, unlike github_int.py's
GitHub-API-based push tracking (which only sees remote-visible repos)."""
from __future__ import annotations

import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

_FIELD_SEP = "\x1f"  # unit separator — won't collide with commit message text


def recent_commits(repo_path: Path, since_hours: int = 24) -> list[dict]:
    """Return commits in repo_path since `since_hours` ago, oldest first.
    Returns [] if repo_path isn't a git repo or git isn't on PATH."""
    since_dt = datetime.now(timezone.utc) - timedelta(hours=since_hours)
    since_iso = since_dt.strftime("%Y-%m-%dT%H:%M:%S")
    try:
        result = subprocess.run(
            ["git", "log", f"--since={since_iso}", "--date=iso-strict",
             f"--pretty=format:%H{_FIELD_SEP}%ad{_FIELD_SEP}%s", "--reverse"],
            cwd=repo_path, capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if result.returncode != 0 or not result.stdout.strip():
        return []

    out: list[dict] = []
    for line in result.stdout.splitlines():
        parts = line.split(_FIELD_SEP)
        if len(parts) != 3:
            continue
        sha, date, message = parts
        out.append({"sha": sha[:7], "date": date, "message": message})
    return out
