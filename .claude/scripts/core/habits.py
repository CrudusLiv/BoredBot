"""HABITS.md auto-detection and late-day nudge.

Pillar names are read dynamically from HABITS.md — add/remove lines there and
the system picks them up automatically. Auto-detection rules and categories live
in .claude/data/habits_config.json.
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_DIR = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[3])
VAULT = PROJECT_DIR / "Dynamous" / "Memory"
HABITS = VAULT / "HABITS.md"
LECTURES = VAULT / "lectures"
NUDGE_STATE = PROJECT_DIR / ".claude" / "data" / "state" / "nudges.json"
HABITS_CONFIG = PROJECT_DIR / ".claude" / "data" / "habits_config.json"

_SCRIPTS_DIR = str(PROJECT_DIR / ".claude" / "scripts")
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from vault import daily  # noqa: E402
from core import habits_state  # noqa: E402

KL = timezone(timedelta(hours=8))
NUDGE_HOUR = 18

_PILLAR_LINE_RE = re.compile(r"^- \[[ xX]\] \*\*(.+?)\*\*", re.MULTILINE)


def _load_config() -> dict:
    if not HABITS_CONFIG.exists():
        return {"auto_detect": {}, "categories": {}, "category_emoji": {}}
    try:
        return json.loads(HABITS_CONFIG.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"auto_detect": {}, "categories": {}, "category_emoji": {}}


def get_pillar_names() -> list[str]:
    """Return pillar names in the order they appear in HABITS.md."""
    if not HABITS.exists():
        return []
    text = HABITS.read_text(encoding="utf-8")
    return _PILLAR_LINE_RE.findall(text)


def _today_kl() -> str:
    return datetime.now(KL).strftime("%Y-%m-%d")


def _now_kl() -> datetime:
    return datetime.now(KL)


def _pillar_line_re(pillar: str) -> re.Pattern[str]:
    return re.compile(
        r"^(- \[)([ xX])(\] \*\*" + re.escape(pillar) + r"\*\*)",
        re.MULTILINE,
    )


def _check_pillar(text: str, pillar: str) -> tuple[str, bool]:
    """Return (new_text, was_changed). Idempotent: already-checked stays checked."""
    pattern = _pillar_line_re(pillar)
    match = pattern.search(text)
    if not match:
        return text, False
    if match.group(2).lower() == "x":
        return text, False
    new_text = pattern.sub(r"\1x\3", text, count=1)
    return new_text, True


def _is_pillar_checked(text: str, pillar: str) -> bool:
    match = _pillar_line_re(pillar).search(text)
    return bool(match and match.group(2).lower() == "x")


# ---------- Auto-detection ----------

def _lectures_touched_today() -> bool:
    if not LECTURES.exists():
        return False
    today = _today_kl()
    for p in LECTURES.rglob("*.md"):
        try:
            mtime = datetime.fromtimestamp(p.stat().st_mtime, tz=KL).strftime("%Y-%m-%d")
        except OSError:
            continue
        if mtime == today:
            return True
    return False


def _commits_today(snapshot: dict) -> bool:
    items = (snapshot.get("github") or {}).get("items") or []
    today = _today_kl()
    for c in items:
        if isinstance(c, dict) and (c.get("date") or "").startswith(today):
            return True
    return False


def classes_today() -> list[dict]:
    """Return today's schedule entries from SCHEDULE.md. Empty list = no classes."""
    try:
        import schedule_parser  # noqa: PLC0415
    except ImportError:
        return []
    view = schedule_parser.schedule_view()
    if not view:
        return []
    today_abbr = datetime.now(KL).strftime("%a")
    return [e for e in view.get("entries", []) if e.get("day") == today_abbr]


def _no_classes_today() -> bool:
    return len(classes_today()) == 0


def _classes_done_today() -> bool:
    """Free day → True. School day → True after last class ends or lecture notes touched."""
    today_classes = classes_today()
    if not today_classes:
        return True
    if _lectures_touched_today():
        return True
    now = _now_kl()
    now_min = now.hour * 60 + now.minute
    ends = []
    for e in today_classes:
        end = e.get("end", "")
        if end and ":" in end:
            try:
                h, m = end.split(":", 1)
                ends.append(int(h) * 60 + int(m))
            except ValueError:
                continue
    return bool(ends) and now_min >= max(ends)


def _sleep_morning_check() -> bool:
    """True from 07:00 KL — auto-fires on the first morning heartbeat."""
    return _now_kl().hour >= 7


def _finance_entry_today() -> bool:
    """True if this month's finance log was modified today."""
    today = _today_kl()
    finance_file = VAULT / "finance" / f"{today[:7]}.md"
    if not finance_file.exists():
        return False
    try:
        mtime = datetime.fromtimestamp(finance_file.stat().st_mtime, tz=KL).strftime("%Y-%m-%d")
        return mtime == today
    except OSError:
        return False


_AUTO_DETECT_FNS: dict[str, str] = {
    "lectures_touched_today": "_lectures_touched_today",
    "commits_today": "_commits_today",
    "no_classes_today": "_no_classes_today",
    "classes_done_today": "_classes_done_today",
    "sleep_morning_check": "_sleep_morning_check",
    "finance_entry_today": "_finance_entry_today",
}


def auto_check(snapshot: dict) -> list[str]:
    """Tick auto-detected pillars in HABITS.md. Returns names of newly-ticked pillars."""
    if not HABITS.exists():
        return []
    config = _load_config()
    auto_detect: dict[str, str] = config.get("auto_detect", {})
    text = HABITS.read_text(encoding="utf-8")
    newly: list[str] = []
    today = _today_kl()

    for pillar, fn_key in auto_detect.items():
        if fn_key == "lectures_touched_today":
            triggered = _lectures_touched_today()
        elif fn_key == "commits_today":
            triggered = _commits_today(snapshot)
        elif fn_key == "no_classes_today":
            triggered = _no_classes_today()
        elif fn_key == "classes_done_today":
            triggered = _classes_done_today()
        elif fn_key == "sleep_morning_check":
            triggered = _sleep_morning_check()
        elif fn_key == "finance_entry_today":
            triggered = _finance_entry_today()
        else:
            continue
        if triggered:
            text, changed = _check_pillar(text, pillar)
            if changed:
                newly.append(pillar)

    if newly:
        HABITS.write_text(text, encoding="utf-8")
        for pillar in newly:
            daily.append_line(f"Habit: {pillar}")
            habits_state.record_completion(today, pillar)
    return newly


# ---------- Manual check-in ----------

def check_pillar(pillar: str) -> bool:
    """Manually check a pillar. Returns True if newly checked, False if already done or not found."""
    if pillar not in get_pillar_names():
        return False
    if not HABITS.exists():
        return False
    text = HABITS.read_text(encoding="utf-8")
    new_text, changed = _check_pillar(text, pillar)
    if not changed:
        return False
    HABITS.write_text(new_text, encoding="utf-8")
    today = _today_kl()
    daily.append_line(f"Habit: {pillar} (manual)")
    habits_state.record_completion(today, pillar)
    return True


# ---------- Status data ----------

def get_status_data() -> dict:
    """Return structured data for building the /habits Discord embed."""
    config = _load_config()
    pillar_names = get_pillar_names()
    text = HABITS.read_text(encoding="utf-8") if HABITS.exists() else ""
    state = habits_state.load_state()
    today = _today_kl()
    today_dt = datetime.strptime(today, "%Y-%m-%d")
    week_start = (today_dt - timedelta(days=today_dt.weekday())).strftime("%Y-%m-%d")
    weekly = habits_state.get_weekly_summary(state["history"], week_start, total=len(pillar_names))
    checked = {p: _is_pillar_checked(text, p) for p in pillar_names}
    done_count = sum(checked.values())
    return {
        "today": today,
        "categories": config.get("categories", {}),
        "category_emoji": config.get("category_emoji", {}),
        "checked": checked,
        "done_count": done_count,
        "total": len(pillar_names),
        "current_streak": state.get("current_streak", 0),
        "best_streak": state.get("best_streak", 0),
        "weekly": weekly,
    }


# ---------- Late-day nudge ----------

def unchecked_pillars() -> list[str]:
    if not HABITS.exists():
        return []
    text = HABITS.read_text(encoding="utf-8")
    return [p for p in get_pillar_names() if not _is_pillar_checked(text, p)]


def _load_nudge_state() -> dict:
    if not NUDGE_STATE.exists():
        return {}
    try:
        return json.loads(NUDGE_STATE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save_nudge_state(state: dict) -> None:
    NUDGE_STATE.parent.mkdir(parents=True, exist_ok=True)
    NUDGE_STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def should_nudge(now: datetime | None = None) -> bool:
    now = now or datetime.now(KL)
    if now.hour < NUDGE_HOUR:
        return False
    state = _load_nudge_state()
    return state.get("last_nudge") != now.strftime("%Y-%m-%d")


def mark_nudged(now: datetime | None = None) -> None:
    now = now or datetime.now(KL)
    _save_nudge_state({"last_nudge": now.strftime("%Y-%m-%d")})


def nudge_message(unchecked: list[str]) -> tuple[str, str]:
    if len(unchecked) == 1:
        title = "Habit nudge"
        body = f"Still unchecked: {unchecked[0]}."
    else:
        title = f"{len(unchecked)} habits unchecked"
        body = "Still open: " + ", ".join(unchecked) + "."
    return title, body
