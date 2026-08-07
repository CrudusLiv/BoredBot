"""Walk projects/ and lectures/, call wikilinks.add_sibling_wikilinks on every
note. Idempotent — safe to re-run. Designed to be invoked after a manual
restructure of either folder."""
from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_DIR = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[2])
sys.path.insert(0, str(PROJECT_DIR / ".claude" / "scripts"))
from memory import wikilinks  # noqa: E402

VAULT = PROJECT_DIR / "Dynamous" / "Memory"
ROOTS = [VAULT / "projects", VAULT / "lectures"]


def main() -> int:
    seen: set[Path] = set()
    for root in ROOTS:
        if not root.exists():
            continue
        for md in root.rglob("*.md"):
            if md in seen:
                continue
            wikilinks.add_sibling_wikilinks(md)
            # The helper writes to every sibling too, so mark them seen.
            seen.add(md)
    print(f"Backfilled wikilinks on {len(seen)} notes (siblings touched implicitly).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
