"""Registry of available integrations + their readiness status.

`status()` is what `query.py status` calls — quick visual check of which
integrations are wired up. Each integration declares the env vars and
files it needs; readiness is computed against the current process env."""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _env  # noqa: F401, E402  -- side effect: loads .env

PROJECT_DIR = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[3])


@dataclass
class Integration:
    name: str
    description: str
    requires_env: list[str] = field(default_factory=list)
    requires_files: list[Path] = field(default_factory=list)
    notes: str = ""

    def ready(self) -> bool:
        return (
            all(os.environ.get(v) for v in self.requires_env)
            and all(f.exists() for f in self.requires_files)
        )

    def missing(self) -> list[str]:
        out: list[str] = []
        for v in self.requires_env:
            if not os.environ.get(v):
                out.append(f"env:{v}")
        for f in self.requires_files:
            if not f.exists():
                out.append(f"file:{f.relative_to(PROJECT_DIR)}".replace("\\", "/"))
        return out


INTEGRATIONS: list[Integration] = [
    Integration(
        name="github",
        description="GitHub repos, PRs, commit diffs",
        requires_env=["GITHUB_TOKEN"],
        notes="Set GITHUB_ASSIGNMENT_REPOS=owner/repo1,owner/repo2 to scope code review.",
    ),
    Integration(
        name="gcal",
        description="Google Calendar (read-only) -- upcoming events",
        requires_env=["GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"],
        notes="Shares OAuth token with Gmail. First run opens browser for consent.",
    ),
    Integration(
        name="gmail",
        description="Gmail inbox (read-only) -- recent messages",
        requires_env=["GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"],
        notes="Shares OAuth token with Google Calendar. First run opens browser for consent.",
    ),
    Integration(
        name="vault",
        description="Local vault filesystem -- inbox watcher for new .pptx and .pdf",
        notes="No auth needed.",
    ),
]


def status() -> str:
    lines = ["Integration status:"]
    width = max(len(i.name) for i in INTEGRATIONS)
    for i in INTEGRATIONS:
        mark = "[OK]" if i.ready() else "[--]"
        lines.append(f"  {mark}  {i.name:{width}}  {i.description}")
        if i.notes:
            lines.append(f"        {' ' * width}  -> {i.notes}")
        miss = i.missing()
        if miss:
            lines.append(f"        {' ' * width}     missing: {', '.join(miss)}")
    return "\n".join(lines)
