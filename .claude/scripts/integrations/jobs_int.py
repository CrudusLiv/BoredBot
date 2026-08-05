"""CLI bridge for the job-alerts scanner -- desktop heartbeat's Node side
shells out here instead of porting voice/jobs.py's Gmail-parsing logic."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
from voice import jobs as voice_jobs  # noqa: E402
from voice import config as voice_config  # noqa: E402


def handle_query(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="query.py jobs")
    parser.add_argument("--json", action="store_true")
    sub = parser.add_subparsers(dest="subcommand", required=True)
    p_scan = sub.add_parser("scan")
    p_scan.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    if args.subcommand == "scan":
        conf = voice_config.load()
        added = voice_jobs.scan_alerts(voice_config.get_data_dir(), conf)
        if args.json:
            print(json.dumps({"added": added}))
        else:
            print(f"Jobs: {added} new posting(s) added.")
    return 0


if __name__ == "__main__":
    sys.exit(handle_query(sys.argv[1:]))
