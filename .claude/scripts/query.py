#!/usr/bin/env python3
"""Unified CLI dispatcher for all Second Brain integrations.

Usage:
    py query.py status                       Show wiring status of every integration

    py query.py github recent-pushes [--days 7]
    py query.py github pr-list [<repo>]
    py query.py github diff <repo> <sha>

    py query.py gcal upcoming [--days 14]

    py query.py gmail recent [--days 7] [--max 30]

    py query.py vault inbox

    py query.py discord recent [--hours 24]
    py query.py discord bot
    py query.py discord prune

Add --json to most subcommands for machine-readable output.

"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / "integrations"))

from integrations import _env  # noqa: F401, E402  -- loads .env
from integrations import (  # noqa: E402
    discord_int,
    gcal_int,
    github_int,
    gmail_int,
    registry,
    vault_fs,
)

DISPATCH = {
    "github": github_int.handle_query,
    "gcal": gcal_int.handle_query,
    "gmail": gmail_int.handle_query,
    "vault": vault_fs.handle_query,
    "discord": discord_int.handle_query,
}


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__.strip())
        return 0
    cmd = argv[0]
    if cmd == "status":
        print(registry.status())
        return 0
    if cmd not in DISPATCH:
        print(f"Unknown integration: {cmd}\n", file=sys.stderr)
        print(__doc__.strip())
        return 1
    return DISPATCH[cmd](argv[1:])


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
