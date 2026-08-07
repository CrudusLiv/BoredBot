"""One-off cleanup: walk inbox/_processed/, delete sources that have
a corresponding valid summary in lectures/ or projects/.

Run manually:
    py .claude/scripts/tools/processed_cleanup.py            # dry-run
    py .claude/scripts/tools/processed_cleanup.py --commit   # actually delete

The matching is lossy: source filename "Lecture_4_-_Iteration.pptx" is
expected to land as "<date>_Lecture_4_-_Iteration.md" somewhere under
lectures/. We match on the source stem appearing anywhere in a .md
filename under the right roots. False negatives are kept; false
positives (matching the wrong note) are still safe because
success_check validates the candidate before deletion.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

PROJECT_DIR = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[3])
sys.path.insert(0, str(PROJECT_DIR / ".claude" / "scripts"))
from integrations import vault_fs  # noqa: E402

VAULT = PROJECT_DIR / "Dynamous" / "Memory"
PROCESSED = VAULT / "inbox" / "_processed"
ROOTS = [VAULT / "lectures", VAULT / "projects"]


def find_match(src_stem: str) -> Path | None:
    for root in ROOTS:
        if not root.exists():
            continue
        for md in root.rglob("*.md"):
            if src_stem in md.stem:
                return md
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true", help="actually delete; default is dry-run")
    args = ap.parse_args()

    if not PROCESSED.exists():
        print("No inbox/_processed/ folder. Nothing to do.")
        return 0

    sources = [p for p in PROCESSED.iterdir() if p.is_file() and p.name != ".gitkeep"]
    if not sources:
        print("inbox/_processed/ is empty.")
        return 0

    deleted = 0
    kept_no_match = 0
    kept_check_failed = 0

    for src in sources:
        match = find_match(src.stem)
        if not match:
            print(f"NO MATCH  {src.name}")
            kept_no_match += 1
            continue
        if not vault_fs.success_check(match):
            print(f"CHECK FAIL {src.name} -> {match.name}")
            kept_check_failed += 1
            continue
        rel = match.relative_to(VAULT).as_posix()
        if args.commit:
            try:
                src.unlink()
                print(f"DELETED   {src.name} (matched {rel})")
                deleted += 1
            except OSError as exc:
                print(f"DELETE FAILED {src.name}: {exc}", file=sys.stderr)
        else:
            print(f"WOULD DEL {src.name} (matched {rel})")
            deleted += 1

    print(
        f"\n{'Deleted' if args.commit else 'Would delete'}: {deleted}  "
        f"No match: {kept_no_match}  Check failed: {kept_check_failed}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
