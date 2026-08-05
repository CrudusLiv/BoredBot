"""CLI bridge for deadline-threshold scanning and calendar->DEADLINES.md
import -- the desktop heartbeat's Node side shells out here instead of
duplicating core/imminent.py or voice/deadlines.py in TypeScript."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from core import imminent  # noqa: E402

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
from voice import deadlines as voice_deadlines  # noqa: E402
from voice import config as voice_config  # noqa: E402
from integrations import gcal_int  # noqa: E402


def scan() -> list[dict]:
    return imminent.actionable(imminent.scan())


def import_from_calendar(days: int = 30) -> list[str]:
    events = gcal_int.upcoming(days, 100)
    keywords = voice_config.load().get("deadline_import_keywords")
    return voice_deadlines.import_from_events(events, keywords)


def handle_query(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="query.py deadlines")
    parser.add_argument("--json", action="store_true")
    sub = parser.add_subparsers(dest="subcommand", required=True)
    p_scan = sub.add_parser("scan")
    p_scan.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    p_import = sub.add_parser("import")
    p_import.add_argument("--days", type=int, default=30)
    p_import.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    if args.subcommand == "scan":
        items = scan()
        if args.json:
            print(json.dumps({"items": items}))
        else:
            for item in items:
                print(f"{item['bucket']}: {item.get('course', '')} {item['title']} ({item['due']})")
    elif args.subcommand == "import":
        added = import_from_calendar(args.days)
        if args.json:
            print(json.dumps({"added": added}))
        else:
            for line in added:
                print(f"+ {line}")
    return 0


if __name__ == "__main__":
    sys.exit(handle_query(sys.argv[1:]))
