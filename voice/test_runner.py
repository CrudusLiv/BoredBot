"""Local pytest runner for the once-daily build/test watcher — this repo
has no per-commit CI (only a manual-tag release build), so the only way
to catch a broken test locally is to actually run the suite."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

_FAILED_RE = re.compile(r"(\d+) failed")
_PASSED_RE = re.compile(r"(\d+) passed")


def _parse_summary(line: str) -> dict:
    failed_match = _FAILED_RE.search(line)
    passed_match = _PASSED_RE.search(line)
    return {
        "passed": int(passed_match.group(1)) if passed_match else 0,
        "failed": int(failed_match.group(1)) if failed_match else 0,
    }


def run_test_suite(repo_root: Path, timeout: int = 300) -> dict:
    """Run `py -m pytest -q` in repo_root. Returns passed/failed counts and
    an `ok` flag. Never raises — a failure to even launch pytest counts as
    not-ok so the caller still gets a notice."""
    try:
        result = subprocess.run(
            ["py", "-m", "pytest", "-q", "tests/"],
            cwd=repo_root, capture_output=True, text=True, timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"passed": 0, "failed": 0, "ok": False, "error": str(exc)}

    summary_line = ""
    for line in reversed(result.stdout.splitlines()):
        if "passed" in line or "failed" in line or "no tests ran" in line:
            summary_line = line
            break
    counts = _parse_summary(summary_line)
    return {**counts, "ok": counts["failed"] == 0}
