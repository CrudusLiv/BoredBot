"""Process-activity signal — thin psutil wrapper enumerating running processes.

Fail-open by design (same contract as voice/idle.py): running_processes()
returns an empty set whenever the signal is unavailable (psutil missing, API
failure, any exception). Callers must treat an empty set as "nothing matched
this poll" and never expect an exception.

Deliberately process-name only — no foreground-window / fullscreen detection.
The heartbeat scans once per poll and feeds the result to both the busy-state
silence gate and the reactive process-trigger check.
"""
from __future__ import annotations


def running_processes() -> set[str]:
    """Return the set of running process executable names, lowercased
    (e.g. {"code.exe", "zoom.exe"}). Empty set on any failure (fails open —
    never raises)."""
    try:
        import psutil  # imported lazily so a missing dep never breaks the heartbeat
    except Exception:
        return set()
    names: set[str] = set()
    try:
        for proc in psutil.process_iter(["name"]):
            try:
                name = proc.info.get("name")
                if name:
                    names.add(name.lower())
            except Exception:
                continue  # process vanished mid-iteration — skip it
    except Exception:
        return set()
    return names


def matched(procs: set[str], names: list[str]) -> set[str]:
    """Case-insensitive intersection of the running-process set with a
    configured list of names. Returns the subset of `names` that are running,
    lowercased. Used by both the silence gate and the trigger check."""
    if not procs or not names:
        return set()
    wanted = {n.lower() for n in names if n}
    return wanted & procs
