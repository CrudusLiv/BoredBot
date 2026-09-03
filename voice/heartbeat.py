"""Background heartbeat — posts notices and queues proactive spoken text.

The loop wakes every context_poll_seconds (default 60 s). Each fast poll
runs the cheap idle-return + activity-awareness checks, then
_run_scheduled(), which fires each task in _SCHEDULE independently once
its own interval has elapsed (see Heartbeat._SCHEDULE). Every check that
can speak is event-triggered and deduped against persisted state — nothing
announces on a bare timer with no underlying change (that was the old
_tick()-based design; see
docs/superpowers/specs/2026-08-07-usability-overhaul-design.md §2 for why
it was replaced).

Notices are written to get_data_dir()/voice_notices.jsonl.
Spoken text is pushed to speak_queue as plain str items.
"""
from __future__ import annotations

import json
import queue as _queue_mod
import re
import threading
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from voice import git_digest, test_runner, todo_tracker

_ROOT = Path(__file__).resolve().parents[1]

import sys as _sys  # noqa: E402

_sys.path.insert(0, str(_ROOT / ".claude" / "scripts"))
from integrations import github_int  # noqa: E402  # type: ignore
from vault import daily as vault_daily  # noqa: E402  # type: ignore
from finance import tracker as finance_tracker  # noqa: E402  # type: ignore
from core import llm as core_llm  # noqa: E402  # type: ignore


def _format_duration(total_minutes: int) -> str:
    """Render a minute count as spoken hours+minutes past 60 (e.g. '1 hour 5 minutes')."""
    if total_minutes < 60:
        return f"{total_minutes} minute{'s' if total_minutes != 1 else ''}"
    hours, mins = divmod(total_minutes, 60)
    parts = [f"{hours} hour{'s' if hours != 1 else ''}"]
    if mins:
        parts.append(f"{mins} minute{'s' if mins != 1 else ''}")
    return " ".join(parts)


def _notices_path() -> Path:
    from voice import config as cfg
    return cfg.get_data_dir() / "voice_notices.jsonl"


# The notices file is append-only; the UI only ever reads the tail (last 50).
# Cap growth for a 24/7 install: once past _NOTICES_MAX_BYTES, rewrite keeping
# the newest _NOTICES_KEEP_LINES lines (atomic tmp+replace, same pattern as
# _env_writer.write_env).
_NOTICES_MAX_BYTES = 256 * 1024
_NOTICES_KEEP_LINES = 500


def _trim_notices(notices: Path) -> None:
    try:
        if notices.stat().st_size <= _NOTICES_MAX_BYTES:
            return
        lines = notices.read_text(encoding="utf-8").splitlines(keepends=True)
        if len(lines) <= _NOTICES_KEEP_LINES:
            return
        tmp = notices.with_name(notices.name + ".tmp")
        tmp.write_text("".join(lines[-_NOTICES_KEEP_LINES:]), encoding="utf-8")
        tmp.replace(notices)
    except OSError:
        pass  # trimming is best-effort; never block posting a notice


# Output suppression while a "busy" process (silence_when_running) is active.
# The flag lives in voice.silence because it gates far more than the heartbeat:
# the wake-word mic and every TTS path read the same predicate. Here it only
# means _post() skips the intrusive OS tray toast and _speak() skips proactive
# speech, while the notice still lands in the jsonl log + web UI so a digest can
# surface it on return.


def _set_output_suppressed(value: bool) -> None:
    from voice import silence
    silence.set_busy(value)


def _output_suppressed() -> bool:
    from voice import silence
    return silence.is_busy()


def _post(text: str, level: str = "INFO", meta: dict | None = None) -> None:
    from voice import config as cfg
    entry = {
        "id": uuid.uuid4().hex[:12],
        "ts": datetime.now(cfg.get_timezone()).isoformat(),
        "text": text,
        "level": level,
        "read": False,
    }
    if meta:
        entry["meta"] = meta
    notices = _notices_path()
    notices.parent.mkdir(parents=True, exist_ok=True)
    with notices.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    _trim_notices(notices)
    try:
        from voice import ui_server
        ui_server.post_event({"type": "notice", **entry})
    except Exception:
        pass
    if not _output_suppressed():
        try:
            from voice import tray
            title = "Vesper [!]" if level == "URGENT" else "Vesper"
            tray.notify(title, text)
        except Exception:
            pass


def _parse_date(value) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except (TypeError, ValueError):
        return None


def _parse_dt(value) -> datetime | None:
    try:
        return datetime.fromisoformat(value) if value else None
    except (TypeError, ValueError):
        return None


def _count_unread() -> int:
    try:
        count = 0
        for line in _notices_path().read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    if not json.loads(line).get("read"):
                        count += 1
                except json.JSONDecodeError:
                    pass
        return count
    except OSError:
        return 0


def _fetch_events(days: int = 1, max_results: int = 10, days_back: int = 0) -> list[dict]:
    """Fetch calendar events; returns [] on any error."""
    try:
        import sys
        sys.path.insert(0, str(_ROOT / ".claude" / "scripts"))
        from integrations import gcal_int  # type: ignore
        return gcal_int.upcoming(days=days, max_results=max_results, days_back=days_back) or []
    except Exception:
        return []


# A real deadline row: `- [nogcal:] YYYY-MM-DD — course — title` (same shape
# core/imminent.py parses). Anything else in DEADLINES.md is prose/instructions
# and must never be spoken as a deadline.
_DEADLINE_ROW_RE = re.compile(r"^[-*]\s*(?:nogcal:\s*)?\d{4}-\d{2}-\d{2}\s+[—–-]\s+\S")

# Markdown bullet + the nogcal: sync marker — file plumbing, never spoken text.
_DEADLINE_PREFIX_RE = re.compile(r"^[-*]\s*(?:nogcal:\s*)?")

_DEADLINE_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")


def _fetch_deadlines() -> list[str]:
    """Return not-yet-past deadline rows from DEADLINES.md as display text
    (bullet and nogcal: marker stripped — every consumer speaks or shows
    them). Past-due rows are _check_deadline_thresholds's job (it announces
    "overdue" once and tracks it separately); this feed backs the "Upcoming"
    briefing lines, so a row that's already due has no business in it.
    [] if no vault configured."""
    try:
        from voice import config as cfg
        vault = cfg.get_vault_dir()
        if vault is None:
            return []
        p = vault / "DEADLINES.md"
        if not p.exists():
            return []
        today = datetime.now(cfg.get_timezone()).date().isoformat()
        rows = []
        for ln in p.read_text(encoding="utf-8").splitlines():
            stripped = ln.strip()
            if not _DEADLINE_ROW_RE.match(stripped):
                continue
            m = _DEADLINE_DATE_RE.search(stripped)
            if m and m.group(1) < today:
                continue
            rows.append(_DEADLINE_PREFIX_RE.sub("", stripped))
        return rows
    except Exception:
        return []


def _fetch_reminders(days: int = 2) -> list[dict]:
    """Fetch Google Tasks reminders (the "Reminders" feature); returns []
    on any error. These live on a separate Tasks list, not the calendar or
    DEADLINES.md, so briefings must query them explicitly."""
    try:
        import sys
        sys.path.insert(0, str(_ROOT / ".claude" / "scripts"))
        from integrations import gtasks_write  # type: ignore
        return gtasks_write.list_reminders(days=days) or []
    except Exception:
        return []


def _fetch_due_reminders() -> list[dict]:
    """Fetch uncompleted Google Tasks reminders already at or past their
    due date (no lower bound, unlike _fetch_reminders' rolling window) --
    the set _check_reminder_nags repeats a voice nag for. [] on any error."""
    try:
        import sys
        sys.path.insert(0, str(_ROOT / ".claude" / "scripts"))
        from integrations import gtasks_write  # type: ignore
        return gtasks_write.due_reminders() or []
    except Exception:
        return []


# Mirrors .claude/hooks/_lib.py's DISTILL_PROMPT (same headers, so the
# vault daily log reads consistently whether an entry came from a coding
# session or a voice conversation) but framed for brain.history instead of
# a Claude Code transcript.
_VOICE_DISTILL_PROMPT = """You are reviewing a day's voice conversation between the user and their
assistant Vesper before it's dropped from memory. Extract only durable items worth remembering
tomorrow. Be ruthless — most chatter is not durable.

Use these exact headers, omit any header with no items:

### Decisions
- one line each, with rationale if given

### Lessons
- what worked, what failed, what to do differently next time

### Facts
- non-obvious things discovered about the user's life, work, or projects

### Open todos
- things the user asked for or implied but that were not finished

If nothing durable happened in this conversation, output exactly: `_(no durable items)_`
No preamble, no commentary, no closing remarks."""


# Plug/unplug voice lines, in Vesper's register. {pct} is the battery
# percentage at the moment of the transition; the _NOPCT fallbacks cover a
# reading with no known percentage (desktop, or BatteryLifePercent == 255).
_POWER_UNPLUG_LINES = [
    "Unplugged. {pct}% in the tank, boss.",
    "Running on battery now — {pct}% left.",
    "Cord's out. {pct}% to work with.",
    "On your own power, {pct}% remaining.",
    "Battery it is — {pct}%.",
]
_POWER_PLUG_LINES = [
    "Plugged in at {pct}%.",
    "Back on the cord — {pct}% and climbing.",
    "Charging now. You were at {pct}%.",
    "Power's in, {pct}% and rising.",
    "Tethered again, {pct}%.",
]
_POWER_UNPLUG_NOPCT = "Unplugged. Running on battery now."
_POWER_PLUG_NOPCT = "Plugged in. Charging now."


class Heartbeat:
    """Background daemon thread. Runs _SCHEDULE's event-triggered checks
    and schedules proactive spoken briefings when speak_queue is provided."""

    # Per-task cadence for _run_scheduled(): (name, method_name,
    # default_interval_minutes, config_key). config_key, if set, overrides
    # the default via voice/config.py. Tasks without a config_key keep
    # today's 30-minute behavior unconditionally.
    _SCHEDULE: list[tuple[str, str, int, str | None]] = [
        ("job_alerts", "_check_job_alerts", 30, None),
        ("morning_briefing", "_morning_briefing", 30, None),
        ("evening_wrap", "_evening_wrap", 30, None),
        # Interval must stay well below nudge_minutes (default 15) or the
        # heads-up window can close between checks and get missed entirely
        # -- see nudge_check_interval_minutes in voice/config.py.
        ("nudges", "_check_nudges", 5, "nudge_check_interval_minutes"),
        ("gcal_sync", "_check_calendar_sync", 5, "gcal_sync_interval_minutes"),
        ("github_digest", "_check_github_digest", 5, "github_digest_interval_minutes"),
        ("urgent_email", "_check_urgent_email", 30, None),
        ("deadline_import", "_check_deadline_import", 30, None),
        ("deadline_thresholds", "_check_deadline_thresholds", 30, None),
        ("git_todo_summary", "_check_git_todo_summary", 30, None),
        ("build_watch", "_check_build_watch", 30, None),
        ("vault_daily_rollup", "_check_vault_daily_rollup", 30, None),
        ("reminder_nags", "_check_reminder_nags", 15, None),
        ("google_auth", "_check_google_auth", 30, None),
    ]

    # Each task's own opt-out flag, for the status panel's enabled/disabled
    # column. morning_briefing/evening_wrap share briefing_enabled since
    # neither has an independent toggle.
    _ENABLED_KEYS: dict[str, str] = {
        "job_alerts": "job_alerts_enabled",
        "morning_briefing": "briefing_enabled",
        "evening_wrap": "briefing_enabled",
        "nudges": "nudge_enabled",
        "gcal_sync": "gcal_sync_enabled",
        "github_digest": "github_digest_enabled",
        "urgent_email": "urgent_email_enabled",
        "deadline_import": "deadline_import_enabled",
        "deadline_thresholds": "deadline_threshold_enabled",
        "git_todo_summary": "git_todo_summary_enabled",
        "build_watch": "build_watch_enabled",
        "vault_daily_rollup": "vault_rollup_enabled",
        "reminder_nags": "reminder_nag_enabled",
        "google_auth": "google_auth_check_enabled",
    }

    # Tasks that actually fire once/day at a configured time-of-day, rather
    # than repeating every _SCHEDULE interval -- that interval is merely how
    # often the cheap "is it time yet" gate is checked (default 30m), not a
    # real repeat cadence. Maps name -> (time_config_key, default_time,
    # done_date_attr) so status_snapshot() can report the real next
    # occurrence instead of the next gate-check. Every other task in
    # _SCHEDULE (job_alerts, gcal_sync, github_digest, urgent_email,
    # deadline_import, deadline_thresholds, nudges, reminder_nags) is a
    # genuine repeating check, so its interval IS the meaningful cadence.
    _DAILY_TASKS: dict[str, tuple[str, str, str]] = {
        "morning_briefing": ("briefing_time", "09:00", "_briefing_done_date"),
        "evening_wrap": ("wrap_time", "21:00", "_wrap_done_date"),
        "git_todo_summary": ("git_todo_summary_time", "20:00", "_git_todo_done_date"),
        "build_watch": ("build_watch_time", "07:30", "_build_watch_done_date"),
        "vault_daily_rollup": ("vault_rollup_time", "23:30", "_vault_rollup_done_date"),
    }

    def __init__(
        self,
        interval_minutes: int = 30,
        speak_queue: "_queue_mod.Queue[str] | None" = None,
        proactive_tts: bool = True,
        context_poll_seconds: int = 60,
        idle_fn=None,
        brain=None,
        power_fn=None,
    ) -> None:
        from voice import idle as _idle
        from voice import power as _power
        self._context_poll_seconds = max(1, int(context_poll_seconds))
        self._idle_fn = idle_fn if idle_fn is not None else _idle.get_idle_seconds
        self._power_fn = power_fn if power_fn is not None else _power.get_power_status
        self._last_run: dict[str, float] = {}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._speak_queue = speak_queue
        self._proactive_tts = proactive_tts
        # Optional Brain reference so _check_vault_daily_rollup can distill
        # brain.history -- None in tests / callers that don't wire it up,
        # in which case the voice-highlights section is just skipped.
        self._brain = brain

        # Idle-return state machine. _away_since is in-memory only (a restart
        # while away just re-detects on the next poll); the fired timestamp
        # persists so a restart doesn't immediately re-fire the notice.
        self._away_since: datetime | None = None

        # Wall-clock timestamp of the last _poll_once() call, tracked
        # unconditionally (even during quiet hours) so a poll-to-poll gap
        # reflects only "the process wasn't running", never quiet-hours
        # gating. See _check_idle_return for why this matters.
        self._last_poll_wallclock: datetime | None = None

        # Activity awareness (process-based silence). In-memory only — a
        # restart just re-baselines on the next poll, same as _away_since.
        self._busy: bool = False
        self._busy_since: datetime | None = None
        self._busy_proc: str | None = None

        # Once-per-day guards persist to heartbeat_state.json so a restart
        # neither re-speaks an already-delivered briefing nor drops a missed
        # one — catch-up happens in _morning_briefing when a past-due date
        # has no delivery recorded.
        state = self._load_state()
        self._briefing_done_date: date | None = _parse_date(state.get("briefing_date"))
        self._wrap_done_date:     date | None = _parse_date(state.get("wrap_date"))
        self._vault_rollup_done_date: date | None = _parse_date(state.get("vault_rollup_date"))

        # Last fixed nag slot fired (ISO datetime, local tz), so a restart
        # doesn't immediately re-fire a slot already delivered. See
        # _check_reminder_nags for the fixed-grid schedule this tracks.
        self._reminder_nag_slot: datetime | None = _parse_dt(state.get("reminder_nag_slot"))
        self._last_idle_return_fired: datetime | None = _parse_dt(state.get("idle_return_fired"))

        # Power plug/unplug trigger. _last_on_ac is in-memory only -- a
        # restart re-baselines silently on the next poll, so relaunching
        # Vesper never fakes a plug/unplug. _last_power_fired persists so a
        # restart loop can't re-announce, and backs the flap cooldown.
        self._last_on_ac: bool | None = None
        self._last_power_fired: datetime | None = _parse_dt(state.get("power_fired"))

        # Nudge deduplication (reset each day)
        self._nudged_events: set[str] = set(state.get("nudged", []))
        self._nudge_reset_date: date | None = _parse_date(state.get("nudged_date"))

        # Migrated proactive-check dedup state (Phase 1 of the roadmap migration).
        self._seen_pr_event_ids: list[str] = list(state.get("seen_pr_event_ids", []))
        self._seen_urgent_email_ids: list[str] = list(state.get("seen_urgent_email_ids", []))
        self._deadline_fired: dict[str, list[str]] = dict(state.get("deadline_fired", {}))
        self._git_todo_done_date: date | None = _parse_date(state.get("git_todo_date"))
        self._build_watch_done_date: date | None = _parse_date(state.get("build_watch_date"))
        self._last_test_ok: bool | None = state.get("last_test_ok")
        self._last_workflow_conclusion: str | None = state.get("last_workflow_conclusion")

        # Google-auth expiry nag: label -> ISO datetime last notified, so a
        # dead sign-in re-nags at most once per 24h and a restart doesn't
        # re-fire it. Cleared per-label once the account reconnects.
        self._google_auth_notified: dict[str, str] = dict(state.get("google_auth_notified", {}))

    @staticmethod
    def _state_path() -> Path:
        from voice import config as cfg
        return cfg.get_data_dir() / "heartbeat_state.json"

    def _load_state(self) -> dict:
        try:
            return json.loads(self._state_path().read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save_state(self) -> None:
        state = {
            "briefing_date": str(self._briefing_done_date) if self._briefing_done_date else None,
            "wrap_date": str(self._wrap_done_date) if self._wrap_done_date else None,
            "vault_rollup_date": str(self._vault_rollup_done_date) if self._vault_rollup_done_date else None,
            "reminder_nag_slot": self._reminder_nag_slot.isoformat() if self._reminder_nag_slot else None,
            "nudged": sorted(self._nudged_events),
            "nudged_date": str(self._nudge_reset_date) if self._nudge_reset_date else None,
            "idle_return_fired": self._last_idle_return_fired.isoformat() if self._last_idle_return_fired else None,
            "power_fired": self._last_power_fired.isoformat() if self._last_power_fired else None,
            "seen_pr_event_ids": self._seen_pr_event_ids,
            "seen_urgent_email_ids": self._seen_urgent_email_ids,
            "deadline_fired": self._deadline_fired,
            "git_todo_date": str(self._git_todo_done_date) if self._git_todo_done_date else None,
            "build_watch_date": str(self._build_watch_done_date) if self._build_watch_done_date else None,
            "last_test_ok": self._last_test_ok,
            "last_workflow_conclusion": self._last_workflow_conclusion,
            "google_auth_notified": self._google_auth_notified,
        }
        try:
            p = self._state_path()
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
            tmp.replace(p)
        except OSError as _e:
            print(f"[heartbeat] state save failed: {_e}", flush=True)

    def _speak(self, text: str) -> None:
        if _output_suppressed():
            return  # busy (silence_when_running active) — hold proactive speech
        if self._speak_queue is not None and self._proactive_tts:
            try:
                self._speak_queue.put_nowait(text)
            except Exception:
                pass

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="vesper-heartbeat"
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        from voice import killswitch
        try:
            if not self._is_quiet() and not killswitch.is_paused():
                self._run_scheduled()
        except Exception as _e:
            print(f"[heartbeat] tick error: {_e}", flush=True)

        while not self._stop.wait(self._context_poll_seconds):
            try:
                if killswitch.is_paused():
                    continue
                self._poll_once()
            except Exception as _e:
                print(f"[heartbeat] tick error: {_e}", flush=True)

    def _poll_once(self) -> None:
        """One fast-cadence poll. Activity awareness (the silent busy-state gate
        + live UI indicator) runs 24/7 so it works even during quiet hours.
        Idle-return and the scheduled briefings/checks stay gated to
        non-quiet hours, so Vesper still never speaks, toasts, or nudges at
        night."""
        now = datetime.now(timezone.utc)
        last_poll = self._last_poll_wallclock
        self._last_poll_wallclock = now
        poll_gap_s = (now - last_poll).total_seconds() if last_poll is not None else 0.0
        try:
            self._check_activity()
        except Exception as _e:
            print(f"[heartbeat] activity check error: {_e}", flush=True)
        if self._is_quiet():
            return
        try:
            self._check_idle_return(poll_gap_s)
        except Exception as _e:
            print(f"[heartbeat] idle check error: {_e}", flush=True)
        try:
            self._check_power_transition()
        except Exception as _e:
            print(f"[heartbeat] power check error: {_e}", flush=True)
        # _run_scheduled() is called every fast poll -- each task in
        # _SCHEDULE self-gates on its own interval, so this is cheap when
        # nothing is due yet (see _run_scheduled's docstring).
        self._run_scheduled()

    def _check_idle_return(self, poll_gap_s: float = 0.0) -> None:
        """Away/return state machine, run every fast poll.

        Away: idle >= threshold → record _away_since (back-dated to when
        idleness actually started). Return: fresh input (idle < 5 s) while
        away → fire the notice, gated by a persisted cooldown so restarts
        and rapid re-idles don't spam.

        poll_gap_s is the wall-clock time since the previous _poll_once()
        call. The tick-based idle signal (voice/idle.py, GetTickCount-based)
        freezes while Windows is suspended, so it under-reports elapsed time
        across a sleep/wake cycle -- a machine asleep for hours can read as
        idle_seconds ~= 0 the moment it wakes. A poll-to-poll gap this large
        can only mean the process itself wasn't running, which sleep is the
        only realistic cause of, so it's treated as an away period on its
        own, independent of idle_seconds."""
        from voice import config as cfg
        conf = cfg.load()
        now = datetime.now(cfg.get_timezone())
        threshold_s = float(conf.get("idle_return_threshold_minutes", 20)) * 60

        if poll_gap_s >= threshold_s:
            gap_start = now - timedelta(seconds=poll_gap_s)
            if self._away_since is None or self._away_since > gap_start:
                self._away_since = gap_start

        idle_seconds = self._idle_fn()
        if idle_seconds is None:
            return  # signal unavailable this poll

        if idle_seconds >= threshold_s:
            if self._away_since is None:
                self._away_since = now - timedelta(seconds=idle_seconds)
            return

        if idle_seconds < 5 and self._away_since is not None:
            away_duration = now - self._away_since
            self._away_since = None
            cooldown = timedelta(minutes=float(conf.get("idle_return_cooldown_minutes", 15)))
            if self._last_idle_return_fired is not None and now - self._last_idle_return_fired < cooldown:
                return
            self._fire_idle_return(conf, away_duration)
            self._last_idle_return_fired = now
            self._save_state()

    def _fire_idle_return(self, conf: dict, away_duration: timedelta) -> None:
        if conf.get("idle_return_enabled", True):
            mins = int(away_duration.total_seconds() // 60)
            parts = [f"Welcome back — you were away for {_format_duration(mins)}."]
            unread = _count_unread()
            if unread:
                parts.append(f"{unread} notice{'s' if unread != 1 else ''} waiting.")
            text = " ".join(parts)
            self._speak(text)
            _post(text)

    def _check_power_transition(self) -> None:
        """Speak once when the laptop moves onto or off AC power. Runs every
        fast poll, inside the same non-quiet-hours gate as idle-return, so
        _speak() self-suppresses while a silence_when_running app is active
        and nothing is spoken at night.

        First reading only baselines _last_on_ac (no line). A real edge fires
        a line unless it lands within power_trigger_cooldown_seconds of the
        last one -- a suppressed edge deliberately leaves _last_on_ac
        untouched, so a loose plug that flaps ends with one line for the
        state it finally settles in."""
        from voice import config as cfg
        conf = cfg.load()
        if not conf.get("power_trigger_enabled", True):
            return
        status = self._power_fn()
        if status is None:
            return
        on_ac = status.get("on_ac")
        if on_ac is None:
            return
        if self._last_on_ac is None:
            self._last_on_ac = on_ac
            return
        if on_ac == self._last_on_ac:
            return

        now = datetime.now(cfg.get_timezone())
        cooldown = timedelta(seconds=float(conf.get("power_trigger_cooldown_seconds", 45)))
        if self._last_power_fired is not None and now - self._last_power_fired < cooldown:
            return

        self._last_on_ac = on_ac
        self._last_power_fired = now
        text = self._power_line(on_ac, status.get("percent"))
        self._speak(text)
        _post(text)
        self._save_state()

    @staticmethod
    def _power_line(on_ac: bool, percent: int | None) -> str:
        import random
        if percent is None:
            return _POWER_PLUG_NOPCT if on_ac else _POWER_UNPLUG_NOPCT
        pool = _POWER_PLUG_LINES if on_ac else _POWER_UNPLUG_LINES
        return random.choice(pool).format(pct=percent)

    def _check_activity(self) -> None:
        """One process scan per fast poll, feeding the busy-state silence gate.
        Opt-in and dormant until activity_awareness_enabled. Fails open
        (activity.running_processes never raises)."""
        from voice import activity, config as cfg
        conf = cfg.load()
        if not conf.get("activity_awareness_enabled", False):
            return
        procs = activity.running_processes()
        self._update_busy_state(conf, procs)

    def _update_busy_state(self, conf: dict, procs: set[str]) -> None:
        """Enter/exit a 'busy' state when a silence_when_running process appears
        or disappears. Entering flips the module output-suppression flag (holds
        proactive voice + tray toasts); exiting clears it and delivers a digest
        of what accrued while busy."""
        from voice import activity
        names = conf.get("silence_when_running") or []
        hits = activity.matched(procs, names)
        now = datetime.now(timezone.utc)
        if hits and not self._busy:
            self._busy = True
            self._busy_since = now
            self._busy_proc = sorted(hits)[0]
            _set_output_suppressed(True)
            self._broadcast_busy(True)
        elif hits and self._busy:
            new_proc = sorted(hits)[0]  # track surviving proc if the first closed
            if new_proc != self._busy_proc:
                self._busy_proc = new_proc
                self._broadcast_busy(True)  # only on change, not every poll
        elif not hits and self._busy:
            proc = self._busy_proc
            self._busy = False
            self._busy_proc = None
            self._busy_since = None
            _set_output_suppressed(False)
            self._broadcast_busy(False)
            self._deliver_busy_digest(conf, proc)

    def _broadcast_busy(self, busy: bool) -> None:
        """Push the busy/silenced state to the orb over the WebSocket so it can
        show a live indicator. Fails open — a UI hiccup must never break the
        heartbeat (same contract as _post)."""
        try:
            from voice import ui_server
            ui_server.post_event({
                "type": "busy_state",
                "busy": busy,
                "proc": self._busy_proc if busy else None,
            })
        except Exception:
            pass

    def _deliver_busy_digest(self, conf: dict, proc: str | None) -> None:
        """On return from a busy stretch, surface the notices that were held.
        Silent when nothing accrued — no point announcing a return with no news.
        Runs only after suppression is cleared so the digest itself is spoken."""
        if not conf.get("activity_awareness_enabled", False):
            return
        if self._is_quiet():
            return  # busy state stays tracked + shown live, but no spoken digest at night
        unread = _count_unread()
        if not unread:
            return
        label = proc or "that app"
        text = (f"You're back from {label} — {unread} "
                f"notice{'s' if unread != 1 else ''} waiting.")
        self._speak(text)
        _post(text)

    def _check_calendar_sync(self) -> None:
        """Push DEADLINES.md rows / gcal: tags to Google Calendar (migrated
        from the old .claude/scripts/heartbeat.py Discord system — the sync
        logic itself is unchanged, only the notify call is new)."""
        from voice import config as cfg
        conf = cfg.load()
        if not conf.get("gcal_sync_enabled", True):
            return
        try:
            import sys
            sys.path.insert(0, str(_ROOT / ".claude" / "scripts"))
            from core import gcal_sync  # type: ignore
            created = gcal_sync.run()
        except Exception as _e:
            print(f"[heartbeat] gcal_sync error: {_e}", flush=True)
            return
        if created:
            text = f"Calendar sync: created {created} new event{'s' if created != 1 else ''}."
            _post(text)

    def _check_github_digest(self) -> None:
        """PR open/merge/comment digest (migrated from the old heartbeat's
        Slice 5 _route_pr_events — same dedup-by-id idea, new state home)."""
        from voice import config as cfg
        conf = cfg.load()
        if not conf.get("github_digest_enabled", True):
            return
        try:
            import sys, time
            sys.path.insert(0, str(_ROOT / ".claude" / "scripts"))
            from integrations import github_int  # type: ignore
            since = time.time() - 24 * 3600
            events = github_int.recent_pr_events(since=since)
        except Exception as _e:
            print(f"[heartbeat] github_digest error: {_e}", flush=True)
            return

        new_events = [e for e in events if e.get("id") and e["id"] not in self._seen_pr_event_ids]
        if not new_events:
            return

        lines = [
            f"{e.get('kind', 'pr')}: {e.get('repo', '')}#{e.get('pr_number', '')} {e.get('pr_title', '')}".strip()
            for e in new_events[:5]
        ]
        _post(f"GitHub: {'; '.join(lines)}"[:280])

        for e in new_events:
            if e["id"] not in self._seen_pr_event_ids:
                self._seen_pr_event_ids.append(e["id"])
        if len(self._seen_pr_event_ids) > 500:
            self._seen_pr_event_ids = self._seen_pr_event_ids[-500:]
        self._save_state()

    def _check_google_auth(self) -> None:
        """Notice when a Google account's cached sign-in has gone dead
        (test-mode refresh tokens expire ~weekly). One URGENT notice when
        it breaks, then no more than once per 24h until it's reconnected
        via the orb's Calendar tab. Inspection only -- account_status()
        never opens a browser."""
        from voice import config as cfg
        conf = cfg.load()
        if not conf.get("google_auth_check_enabled", True):
            return
        _sys.path.insert(0, str(_ROOT / ".claude" / "scripts"))
        try:
            from integrations import google_auth  # type: ignore
        except Exception as _e:
            print(f"[heartbeat] google_auth check error: {_e}", flush=True)
            return

        now = datetime.now(cfg.get_timezone())
        renag = timedelta(hours=24)
        changed = False
        for account in google_auth.list_accounts():
            label = account or "primary"
            try:
                status = google_auth.account_status(account)
            except Exception as _e:
                print(f"[heartbeat] google_auth status({label}) error: {_e}", flush=True)
                continue
            if status.get("needs_reconnect"):
                last = _parse_dt(self._google_auth_notified.get(label))
                if last is None or now - last >= renag:
                    _post(
                        f"Google sign-in for {label} expired -- reconnect in the Calendar tab.",
                        level="URGENT",
                    )
                    self._google_auth_notified[label] = now.isoformat()
                    changed = True
            elif label in self._google_auth_notified:
                del self._google_auth_notified[label]
                changed = True
        if changed:
            self._save_state()

    def _check_urgent_email(self) -> None:
        """Speak only when a genuinely new urgent-flagged email appears
        (id-based dedup). Replaces the old _tick()-driven 'N new message(s)'
        announcement, which re-fired on every count change whether or not
        anything in the inbox actually needed attention."""
        from voice import config as cfg
        conf = cfg.load()
        if not conf.get("urgent_email_enabled", True):
            return
        try:
            import sys
            sys.path.insert(0, str(_ROOT / ".claude" / "scripts"))
            from integrations import gmail_int  # type: ignore
            from voice.tools.email import URGENT_KEYWORDS
            days = int(conf.get("urgent_email_lookback_days", 1))
            emails = gmail_int.list_recent(days=days, max_results=20)
        except Exception as _e:
            print(f"[heartbeat] urgent_email error: {_e}", flush=True)
            return

        new_urgent = []
        for e in emails:
            eid = e.get("id")
            if not eid or eid in self._seen_urgent_email_ids:
                continue
            subj = (e.get("subject") or "").lower()
            snip = (e.get("snippet") or "").lower()
            if any(k in subj or k in snip for k in URGENT_KEYWORDS):
                new_urgent.append(e)

        if not new_urgent:
            return

        lines = [f"{e.get('from', '?')} — {e.get('subject', '(no subject)')}" for e in new_urgent[:3]]
        _post(f"Urgent email: {'; '.join(lines)}"[:280], level="URGENT")

        for e in new_urgent:
            self._seen_urgent_email_ids.append(e["id"])
        if len(self._seen_urgent_email_ids) > 500:
            self._seen_urgent_email_ids = self._seen_urgent_email_ids[-500:]
        self._save_state()

    _DEADLINE_BUCKET_KIND: dict[str, str] = {
        "approaching": "72h",
        "soon": "72h",
        "urgent": "24h",
        "overdue": "overdue",
    }

    def _check_deadline_thresholds(self) -> None:
        """72h/24h/overdue deadline-crossing notices (migrated from the old
        heartbeat's Slice 3 _route_deadlines — no more per-row Discord
        threads, just a flat per-key 'thresholds already posted' list)."""
        from voice import config as cfg
        conf = cfg.load()
        if not conf.get("deadline_threshold_enabled", True):
            return
        try:
            import sys
            sys.path.insert(0, str(_ROOT / ".claude" / "scripts"))
            from core import imminent  # type: ignore
            buckets = imminent.scan()
            items = imminent.actionable(buckets)
        except Exception as _e:
            print(f"[heartbeat] deadline_threshold error: {_e}", flush=True)
            return

        changed = False
        for item in items:
            threshold = self._DEADLINE_BUCKET_KIND.get(item.get("bucket", ""))
            if threshold is None:
                continue
            key = item.get("key", "")
            fired = self._deadline_fired.setdefault(key, [])
            if threshold in fired:
                continue
            course = item.get("course") or ""
            title = item.get("title") or "(untitled)"
            label = f"{course} — {title}" if course else title
            _post(f"Deadline ({threshold}): {label}", level="URGENT" if threshold != "72h" else "INFO")
            fired.append(threshold)
            changed = True

        if changed:
            self._save_state()

    def _check_git_todo_summary(self) -> None:
        """Once-daily local commit + open-todo digest — genuinely new
        capability, no equivalent existed in the old Discord heartbeat
        (that system's commit tracking was GitHub-API/remote-repo based;
        this reads the local working tree directly)."""
        from voice import config as cfg
        conf = cfg.load()
        if not conf.get("git_todo_summary_enabled", True):
            return

        now = datetime.now(cfg.get_timezone())
        today = now.date()
        if self._git_todo_done_date == today:
            return
        sh, sm = (int(x) for x in conf.get("git_todo_summary_time", "20:00").split(":"))
        if now.hour < sh or (now.hour == sh and now.minute < sm):
            return

        self._git_todo_done_date = today
        self._save_state()

        commits = git_digest.recent_commits(_ROOT, since_hours=24)
        vault = cfg.get_vault_dir()
        todos = todo_tracker.unchecked_todos(vault) if vault else []

        if not commits and not todos:
            return
        parts = []
        if commits:
            parts.append(f"{len(commits)} commit{'s' if len(commits) != 1 else ''} today")
        if todos:
            parts.append(f"{len(todos)} todo{'s' if len(todos) != 1 else ''} still open: {'; '.join(todos[:3])}")
        _post("Daily summary: " + "; ".join(parts))

    def _check_build_watch(self) -> None:
        """Once-daily local test-suite run + release-workflow status check.
        This repo has no per-commit CI (build.yml only runs on version
        tags), so a proactive local pytest run is the only way to catch a
        regression before it's committed. Notifies on failure only."""
        from voice import config as cfg
        conf = cfg.load()
        if not conf.get("build_watch_enabled", True):
            return

        now = datetime.now(cfg.get_timezone())
        today = now.date()
        if self._build_watch_done_date == today:
            return
        bh, bm = (int(x) for x in conf.get("build_watch_time", "07:30").split(":"))
        if now.hour < bh or (now.hour == bh and now.minute < bm):
            return

        self._build_watch_done_date = today

        test_result = test_runner.run_test_suite(_ROOT)
        if not test_result.get("ok", True):
            failed = test_result.get("failed", 0)
            _post(f"Build watch: {failed} test{'s' if failed != 1 else ''} failing locally.", level="URGENT")
        self._last_test_ok = test_result.get("ok")

        repo = conf.get("build_watch_repo", "")
        if repo:
            try:
                run = github_int.latest_workflow_run(repo)
            except Exception as _e:
                print(f"[heartbeat] build_watch workflow error: {_e}", flush=True)
                run = None
            if run and run.get("conclusion") == "failure":
                _post(f"Build watch: last release build failed — {run.get('html_url', '')}", level="URGENT")
            self._last_workflow_conclusion = run.get("conclusion") if run else None

        self._save_state()

    def _check_vault_daily_rollup(self) -> None:
        """Once-daily append to Dynamous/Memory/daily/YYYY-MM-DD.md, rolling
        up the three things that otherwise never reach the vault: voice
        conversation highlights (brain.history, distilled the same way
        .claude/hooks/_lib.py distills a coding-session transcript), the
        day's heartbeat notices (voice_notices.jsonl ages out of the
        runtime data dir), and a finance summary. Runs late by default
        (vault_rollup_time) so it has as much of the day as possible to
        summarize; same once-per-day dedup pattern as _evening_wrap."""
        from voice import config as cfg
        conf = cfg.load()
        if not conf.get("vault_rollup_enabled", True):
            return

        now = datetime.now(cfg.get_timezone())
        today = now.date()
        if self._vault_rollup_done_date == today:
            return
        rh, rm = (int(x) for x in conf.get("vault_rollup_time", "23:30").split(":"))
        if now.hour < rh or (now.hour == rh and now.minute < rm):
            return

        self._vault_rollup_done_date = today
        self._save_state()

        sections: list[tuple[str, str]] = []
        voice_block = self._distill_voice_history()
        if voice_block:
            sections.append(("Voice conversation", voice_block))
        digest_block = self._heartbeat_digest_text(today)
        if digest_block:
            sections.append(("Heartbeat digest", digest_block))
        finance_block = self._finance_rollup_text(now)
        if finance_block:
            sections.append(("Finance", finance_block))

        for label, content in sections:
            try:
                vault_daily.append_block(label, content)
            except OSError as _e:
                print(f"[heartbeat] vault rollup write failed ({label}): {_e}", flush=True)

    def _distill_voice_history(self) -> str:
        """Durable-items distillation of today's voice conversation, same
        shape as the coding-session hooks. "" if there's no brain wired up,
        no conversation happened, or nothing durable came of it."""
        if self._brain is None:
            return ""
        history = list(getattr(self._brain, "history", []) or [])
        if not history:
            return ""
        transcript = "\n".join(
            f"{str(turn.get('role', '')).upper()}: {turn.get('content', '')}"
            for turn in history if turn.get("content")
        )
        if not transcript.strip():
            return ""
        try:
            if not core_llm.is_available():
                return ""
            text = (core_llm.call(transcript, system_prompt=_VOICE_DISTILL_PROMPT, model="haiku") or "").strip()
        except Exception as _e:
            print(f"[heartbeat] voice distillation error: {_e}", flush=True)
            return ""
        if not text or text.startswith("_(no durable items)_") or text.startswith("_(distillation"):
            return ""
        return text

    def _heartbeat_digest_text(self, today: date) -> str:
        """Bullet list of today's notices from voice_notices.jsonl -- the
        runtime log the orb UI reads, which gets trimmed over time and was
        never otherwise kept anywhere durable."""
        today_str = today.isoformat()
        lines: list[str] = []
        try:
            for line in _notices_path().read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                ts = str(entry.get("ts", ""))
                if not ts.startswith(today_str):
                    continue
                lines.append(f"- [{ts[11:16]}] {entry.get('text', '')}")
        except OSError:
            return ""
        return "\n".join(lines)

    def _finance_rollup_text(self, now: datetime) -> str:
        """Today's finance summary via finance/tracker.py's own formatting
        logic (day_summary), so the row format stays single-sourced there."""
        try:
            return finance_tracker.day_summary(now)
        except Exception as _e:
            print(f"[heartbeat] finance rollup error: {_e}", flush=True)
            return ""

    def _check_reminder_nags(self) -> None:
        """Speak every due-or-overdue Google Tasks reminder together on a
        fixed clock grid anchored at briefing_time (default 09:00,
        matching the morning briefing's start-of-day) and repeating every
        reminder_nag_interval_minutes (default 2h) -- e.g. 9, 11, 1, 3...
        local time -- rather than each reminder tracking its own rolling
        timer from whenever it first became due. Repeats until marked done
        -- voice: "mark <title> done" (complete_reminder_tool), or
        complete_reminder_tool directly. The last fired slot persists
        across restarts (heartbeat_state.json) so a restart never re-fires
        a slot already delivered."""
        from voice import config as cfg
        conf = cfg.load()
        if not conf.get("reminder_nag_enabled", True):
            return
        reminders = _fetch_due_reminders()
        if not reminders:
            return

        now_local = datetime.now(cfg.get_timezone())
        bh, bm = (int(x) for x in conf.get("briefing_time", "09:00").split(":"))
        anchor = now_local.replace(hour=bh, minute=bm, second=0, microsecond=0)
        interval_min = float(conf.get("reminder_nag_interval_minutes", 120))

        # Floor-divide to the most recent grid slot at-or-before now, so the
        # schedule holds whether now is before or after today's anchor time.
        slots_elapsed = ((now_local - anchor).total_seconds() / 60) // interval_min
        slot = anchor + timedelta(minutes=slots_elapsed * interval_min)

        if self._reminder_nag_slot is not None and slot <= self._reminder_nag_slot:
            return

        for r in reminders:
            title = r.get("title") or "(reminder)"
            text = f'Reminder still open: {title}. Say "mark it done" once it\'s handled.'
            self._speak(text)
            _post(text)

        self._reminder_nag_slot = slot
        self._save_state()

    def _check_job_alerts(self) -> None:
        """Scan Gmail for job-alert digests and accumulate postings into the
        jobs store. Silent by design — no notice fires; the Jobs panel in the
        orb UI is checked on the user's own schedule."""
        from voice import config as cfg
        from voice import jobs
        conf = cfg.load()
        if not conf.get("job_alerts_enabled", False):
            return
        try:
            jobs.scan_alerts(cfg.get_data_dir(), conf)
        except Exception as _e:
            print(f"[heartbeat] job alerts error: {_e}", flush=True)

    def _check_deadline_import(self) -> None:
        """Calendar events that look like deadlines (per the keyword list)
        become nogcal: rows in DEADLINES.md, so threshold alerts cover them.
        Also reconciles the other direction: a nogcal row whose source event
        was deleted straight from Google Calendar (not through Vesper) gets
        pruned here too, so it stops alerting forever with no way to clear."""
        from voice import config as cfg
        from voice import deadlines
        conf = cfg.load()
        if not conf.get("deadline_import_enabled", True):
            return
        days = int(conf.get("deadline_import_lookahead_days", 30))
        days_back = int(conf.get("deadline_import_lookback_days", 3))
        events = _fetch_events(days=days, max_results=100, days_back=days_back)
        added, removed = deadlines.sync_with_calendar(
            events, conf.get("deadline_import_keywords"),
            days_back=days_back, days_forward=days,
        )
        if added:
            _post(("Deadlines from calendar: " + "; ".join(added))[:160])
        if removed:
            _post(("Deadlines cleared (removed from calendar): " + "; ".join(removed))[:160])

    def status_snapshot(self) -> dict:
        """Point-in-time state for the orb's status panel: the busy/silence
        gate (also used to correct a stale UI on page load/reconnect, since
        the WS only pushes busy_state on transition) plus per-task cadence
        and last-run info.

        _DAILY_TASKS tasks report their real next occurrence at a
        configured time-of-day (today's target time if not yet done and
        not yet passed; "now" -- imminent, fires on the next poll -- if
        passed and not done today; tomorrow's target time if already done
        today). Every other task reports the next _SCHEDULE gate-check,
        which for those is when the actual repeating work happens, so it's
        already the meaningful number. Safe to call from any thread."""
        from voice import config as cfg
        conf = cfg.load()
        now_mono = time.monotonic()
        now_local = datetime.now(cfg.get_timezone())
        now_utc = datetime.now(timezone.utc)
        tasks = []
        for name, _method, default_min, cfg_key in self._SCHEDULE:
            interval_min = int(conf.get(cfg_key, default_min) if cfg_key else default_min)
            enabled_key = self._ENABLED_KEYS.get(name)
            enabled = bool(conf.get(enabled_key, True)) if enabled_key else True

            if name in self._DAILY_TASKS:
                time_key, default_time, done_attr = self._DAILY_TASKS[name]
                hh, mm = (int(x) for x in str(conf.get(time_key, default_time)).split(":"))
                done_date = getattr(self, done_attr, None)
                target_today = now_local.replace(hour=hh, minute=mm, second=0, microsecond=0)
                last_run_iso = (
                    datetime.combine(done_date, target_today.timetz()).isoformat()
                    if done_date is not None else None
                )
                if done_date == now_local.date():
                    next_occurrence = target_today + timedelta(days=1)
                else:
                    next_occurrence = target_today if now_local < target_today else now_local
                tasks.append({
                    "name": name,
                    "enabled": enabled,
                    "schedule_kind": "daily",
                    "cadence_label": f"daily at {hh:02d}:{mm:02d}",
                    "last_run": last_run_iso,
                    "due_in_seconds": max(0, int((next_occurrence - now_local).total_seconds())),
                })
                continue

            interval_s = interval_min * 60
            last = self._last_run.get(name)
            last_run_iso = None
            due_in_s = 0
            if last is not None:
                age_s = now_mono - last
                last_run_iso = (now_utc - timedelta(seconds=age_s)).isoformat()
                due_in_s = max(0, int(interval_s - age_s))
            tasks.append({
                "name": name,
                "enabled": enabled,
                "schedule_kind": "interval",
                "cadence_label": f"every {interval_min}m",
                "last_run": last_run_iso,
                "due_in_seconds": due_in_s,
            })
        return {
            "busy": self._busy,
            "busy_proc": self._busy_proc,
            "tasks": tasks,
        }

    def _run_scheduled(self) -> None:
        """Run each _SCHEDULE task independently once its own interval has
        elapsed (config-overridable for gcal_sync/github_digest, else a
        fixed default -- see _SCHEDULE). Called every fast poll; tasks not
        yet due are skipped cheaply. time.monotonic() keeps interval
        tracking immune to wall-clock jumps (sleep/resume, DST)."""
        from voice import config as cfg
        conf = cfg.load()
        now = time.monotonic()
        for name, method_name, default_min, cfg_key in self._SCHEDULE:
            interval_min = conf.get(cfg_key, default_min) if cfg_key else default_min
            interval_s = interval_min * 60
            last = self._last_run.get(name)
            if last is not None and now - last < interval_s:
                continue
            # Set before calling, not after a successful return -- a
            # persistently-failing task must wait out its normal interval
            # rather than being retried every poll.
            self._last_run[name] = now
            try:
                getattr(self, method_name)()
            except Exception as _e:
                print(f"[heartbeat] {method_name} error: {_e}", flush=True)

    def _morning_briefing(self) -> None:
        from voice import config as cfg
        conf = cfg.load()
        if not conf.get("briefing_enabled", True):
            return

        now = datetime.now(cfg.get_timezone())
        today = now.date()
        if self._briefing_done_date == today:
            return

        bh, bm = (int(x) for x in conf.get("briefing_time", "09:00").split(":"))
        if now.hour < bh or (now.hour == bh and now.minute < bm):
            return

        # Lateness: >1h past briefing_time means we were down/asleep when it
        # was due — deliver a catch-up variant unless it has gone stale.
        lateness_h = (now - now.replace(hour=bh, minute=bm, second=0, microsecond=0)).total_seconds() / 3600
        catchup = False
        if lateness_h > 1:
            if not conf.get("catchup_briefing", True) or \
                    lateness_h > float(conf.get("catchup_max_age_hours", 12)):
                self._briefing_done_date = today
                self._save_state()
                return
            catchup = True

        self._briefing_done_date = today
        self._save_state()

        if catchup:
            parts = ["While you were away —"]
            unread = _count_unread()
            if unread:
                parts.append(f"{unread} notice{'s' if unread != 1 else ''} waiting.")
        else:
            parts = ["Good morning."]
        # The 24h fetch window straddles midnight, so tomorrow's all-day
        # events land in it — bucket by actual start date or the briefing
        # calls tomorrow's birthday "today".
        events = _fetch_events(days=1, max_results=5)
        today_strs: list[str] = []
        tomorrow_strs: list[str] = []
        for e in events:
            start = e.get("start", "")
            if "T" in start:
                label = f"{e.get('summary', '(no title)')} at {start[11:16]}"
            else:
                label = f"{e.get('summary', '(no title)')} (all day)"
            bucket = today_strs if start[:10] == str(today) else tomorrow_strs
            bucket.append(label)
        tomorrow = today + timedelta(days=1)
        for r in _fetch_reminders(days=2):
            due = (r.get("due") or "")[:10]
            label = f"{r.get('title', '(reminder)')} (reminder)"
            if due == str(today):
                today_strs.append(label)
            elif due == str(tomorrow):
                tomorrow_strs.append(label)
        if today_strs:
            parts.append(f"Today: {', '.join(today_strs[:3])}.")
        else:
            parts.append("No events today.")
        if tomorrow_strs:
            parts.append(f"Tomorrow: {', '.join(tomorrow_strs[:3])}.")

        deadlines = _fetch_deadlines()
        if deadlines:
            parts.append(f"Upcoming: {'; '.join(deadlines[:2])}.")

        text = " ".join(parts)
        self._speak(text)
        _post(text)

    def _evening_wrap(self) -> None:
        from voice import config as cfg
        conf = cfg.load()
        if not conf.get("briefing_enabled", True):
            return

        now = datetime.now(cfg.get_timezone())
        today = now.date()
        if self._wrap_done_date == today:
            return

        wh, wm = (int(x) for x in conf.get("wrap_time", "21:00").split(":"))
        if now.hour < wh or (now.hour == wh and now.minute < wm):
            return

        self._wrap_done_date = today
        self._save_state()

        parts: list[str] = ["Evening check-in."]
        tomorrow = today + timedelta(days=1)
        events = _fetch_events(days=2, max_results=10)
        tmr = [e for e in events if e.get("start", "")[:10] == str(tomorrow)]
        reminders_tmr = [r for r in _fetch_reminders(days=2) if (r.get("due") or "")[:10] == str(tomorrow)]
        if tmr:
            first = tmr[0]
            summary = first.get("summary", "(no title)")
            if "T" in first.get("start", ""):
                parts.append(f"Tomorrow starts with {summary} at {first['start'][11:16]}.")
            else:
                parts.append(f"Tomorrow: {summary}, all day.")
            if reminders_tmr:
                titles = ", ".join(r.get("title", "(reminder)") for r in reminders_tmr[:3])
                parts.append(f"Also {len(reminders_tmr)} reminder{'s' if len(reminders_tmr) != 1 else ''}: {titles}.")
        elif reminders_tmr:
            titles = ", ".join(r.get("title", "(reminder)") for r in reminders_tmr[:3])
            parts.append(
                f"Nothing on the calendar tomorrow, but {len(reminders_tmr)} "
                f"reminder{'s' if len(reminders_tmr) != 1 else ''}: {titles}."
            )
        else:
            parts.append("Nothing scheduled for tomorrow.")

        deadlines = _fetch_deadlines()
        if deadlines:
            parts.append(f"Don't forget: {deadlines[0]}.")

        text = " ".join(parts)
        self._speak(text)
        _post(text)

    def _check_nudges(self) -> None:
        from voice import config as cfg
        conf = cfg.load()
        if not conf.get("nudge_enabled", True):
            return

        nudge_min = int(conf.get("nudge_minutes", 15))
        now = datetime.now(cfg.get_timezone())
        today = now.date()

        if self._nudge_reset_date != today:
            self._nudged_events.clear()
            self._nudge_reset_date = today
            self._save_state()

        for event in _fetch_events(days=1, max_results=10):
            key = f"{event.get('start', '')}|{event.get('summary', '')}"
            if key in self._nudged_events:
                continue
            start_str = event.get("start", "")
            if "T" not in start_str:
                continue  # all-day event — no time-based nudge
            try:
                event_dt = datetime.fromisoformat(start_str)
                if event_dt.tzinfo is None:
                    event_dt = event_dt.replace(tzinfo=cfg.get_timezone())
                delta = (event_dt - now).total_seconds() / 60
                if 0 < delta <= nudge_min:
                    self._nudged_events.add(key)
                    self._save_state()
                    mins = int(delta)
                    text = (
                        f"Heads up — {event.get('summary', 'an event')} starts in "
                        f"{_format_duration(mins)}."
                    )
                    self._speak(text)
                    _post(text, level="URGENT")
            except Exception:
                continue

    @staticmethod
    def _is_quiet() -> bool:
        try:
            from voice import config as cfg
            return cfg.is_quiet_hours()
        except Exception:
            return False
