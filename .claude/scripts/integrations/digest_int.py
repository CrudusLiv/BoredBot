"""CLI bridge for the once-daily git/todo and build-watch digests -- the
desktop heartbeat's Node side shells out here instead of porting the local
pytest runner or git log parsing to TypeScript."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from integrations import github_int  # noqa: E402

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
from voice import git_digest, todo_tracker, test_runner  # noqa: E402
from voice import config as voice_config  # noqa: E402


def handle_query(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="query.py digest")
    parser.add_argument("--json", action="store_true")
    sub = parser.add_subparsers(dest="subcommand", required=True)
    p_gt = sub.add_parser("git-todo")
    p_gt.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    p_bw = sub.add_parser("build-watch")
    p_bw.add_argument("--repo", default="")
    p_bw.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    if args.subcommand == "git-todo":
        commits = git_digest.recent_commits(_ROOT, since_hours=24)
        vault = voice_config.get_vault_dir()
        todos = todo_tracker.unchecked_todos(vault) if vault else []
        result = {"commits": commits, "todos": todos}
        if args.json:
            print(json.dumps(result, default=str))
        else:
            print(f"{len(commits)} commit(s), {len(todos)} open todo(s)")
    elif args.subcommand == "build-watch":
        test_result = test_runner.run_test_suite(_ROOT)
        workflow = github_int.latest_workflow_run(args.repo) if args.repo else None
        result = {"test": test_result, "workflow": workflow}
        if args.json:
            print(json.dumps(result, default=str))
        else:
            print(f"tests ok={test_result.get('ok')} workflow={workflow}")
    return 0


if __name__ == "__main__":
    sys.exit(handle_query(sys.argv[1:]))
