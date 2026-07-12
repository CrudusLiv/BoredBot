"""Background heartbeat — posts notices and queues proactive spoken text.

The loop wakes every context_poll_seconds (default 60 s) for the cheap
idle-return check; the expensive checks below still run on the original
heartbeat_interval_minutes cadence via a tick counter.

Per slow tick (every heartbeat_interval_minutes, default 30):
  1. Upcoming calendar events (today via gcal_int)
  2. Unread email count (gmail_int)
  3. Upcoming deadlines (DEADLINES.md in the configured vault, if any)

When speak_queue is provided and proactive_tts is true:
  4. Morning briefing (once per day at briefing_time)
  5. Evening wrap-up (once per day at wrap_time)
  6. Pre-event nudge (nudge_minutes before each calendar event)

Notices are written to get_data_dir()/voice_notices.jsonl.
Spoken text is pushed to speak_queue as plain str items.
"""
from __future__ import annotations

import contextlib
import io
import json
import queue as _queue_mod
import re
import threading
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from voice import git_digest, spaced_repetition, test_runner, todo_tracker

_ROOT = Path(__file__).resolve().parents[1]

import sys as _sys  # noqa: E402

_sys.path.insert(0, str(_ROOT / ".claude" / "scripts"))
from integrations import github_int  # noqa: E402  # type: ignore


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


# Output suppression — set True by the heartbeat while a "busy" process
# (silence_when_running) is active. _post() then skips the intrusive OS tray
# toast and _speak() skips proactive speech, while the notice still lands in the
# jsonl log + web UI so a digest can surface it on return. Module-level because
# _post is a module function, not a Heartbeat method.
_OUTPUT_SUPPRESSED = False


def _set_output_suppressed(value: bool) -> None:
    global _OUTPUT_SUPPRESSED
    _OUTPUT_SUPPRESSED = bool(value)


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
    if not _OUTPUT_SUPPRESSED:
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


def _fetch_events(days: int = 1, max_results: int = 10) -> list[dict]:
    """Fetch calendar events; returns [] on any error."""
    try:
        import sys
        sys.path.insert(0, str(_ROOT / ".claude" / "scripts"))
        from integrations import gcal_int  # type: ignore
        return gcal_int.upcoming(days=days, max_results=max_results) or []
    except Exception:
        return []


# A real deadline row: `- [nogcal:] YYYY-MM-DD — course — title` (same shape
# core/imminent.py parses). Anything else in DEADLINES.md is prose/instructions
# and must never be spoken as a deadline.
_DEADLINE_ROW_RE = re.compile(r"^[-*]\s*(?:nogcal:\s*)?\d{4}-\d{2}-\d{2}\s+[—–-]\s+\S")


def _fetch_deadlines() -> list[str]:
    """Return deadline rows from DEADLINES.md. [] if no vault configured."""
    try:
        from voice import config as cfg
        vault = cfg.get_vault_dir()
        if vault is None:
            return []
        p = vault / "DEADLINES.md"
        if not p.exists():
            return []
        return [
            ln.strip()
            for ln in p.read_text(encoding="utf-8").splitlines()
            if _DEADLINE_ROW_RE.match(ln.strip())
        ]
    except Exception:
        return []


def _check_calendar() -> list[str]:
    try:
        events = _fetch_events(days=1, max_results=10)
        if not events:
            return []
        lines = [f"{e.get('start', '')[:16]}  {e.get('summary', '(no title)')}" for e in events[:3]]
        return [f"Calendar: {'; '.join(lines)}"[:120]]
    except Exception:
        return []


def _check_email() -> list[str]:
    _sink = io.StringIO()
    try:
        import sys
        sys.path.insert(0, str(_ROOT / ".claude" / "scripts"))
        from integrations import gmail_int  # type: ignore
        with contextlib.redirect_stdout(_sink), contextlib.redirect_stderr(_sink):
            msgs = gmail_int.list_recent(days=1, max_results=5)
        if msgs:
            return [f"Email: {len(msgs)} new message(s) in the last 24h"]
    except Exception:
        pass
    return []


def _check_deadlines() -> list[str]:
    lines = _fetch_deadlines()
    if lines:
        snippet = "; ".join(lines[:2])
        return [f"Deadlines: {snippet[:120]}"]
    return []


def _tick() -> None:
    notices: list[str] = []
    notices.extend(_check_calendar())
    notices.extend(_check_email())
    notices.extend(_check_deadlines())
    for text in notices:
        _post(text)


def process_inbox_once() -> None:
    """Run one inbox-processing pass immediately (outside the heartbeat's own
    tick cadence). Shared by Heartbeat._process_inbox and the downloads-triage
    file endpoint, so approving a download doesn't wait for the next slow tick."""
    from voice import config as cfg
    conf = cfg.load()
    if not conf.get("inbox_processing_enabled", True):
        return
    if cfg.get_vault_dir() is None:
        return
    try:
        import sys
        sys.path.insert(0, str(_ROOT / ".claude" / "scripts"))
        from core import inbox, deadlines  # type: ignore

        summaries = inbox.process_new_files()
        all_deadlines: list[dict] = []
        for summary in summaries:
            stype = summary.get("type")
            if stype == "lecture":
                label = "Lecture summarised"
            elif stype == "screenshot":
                label = "Screenshot OCR'd"
            else:
                label = "Project filed"
            bucket = summary.get("name", "")
            if summary.get("subcategory"):
                bucket += f" / {summary['subcategory']}"
            title = summary.get("title", "")
            _post(f"{label}: {bucket} — {title}" if bucket else f"{label}: {title}")
            if summary.get("roadmap_notice"):
                _post(summary["roadmap_notice"])
            if summary.get("type") == "lecture":
                try:
                    from agents import quiz_generator  # type: ignore
                    from voice import spaced_repetition as sr
                    cards = quiz_generator.run(from_path=str(summary["path"]))
                    if cards:
                        sr.add_cards(summary.get("name", ""), cards)
                except Exception as _e:
                    print(f"[heartbeat] quiz generation error: {_e}", flush=True)
            all_deadlines.extend(summary.get("deadlines") or [])

        promoted = deadlines.promote(all_deadlines)
        if promoted:
            _post(f"Promoted {promoted} deadline{'s' if promoted != 1 else ''} to DEADLINES.md")

        inbox.refresh_daily_timeline()
    except Exception as _e:
        print(f"[heartbeat] inbox processing error: {_e}", flush=True)


class Heartbeat:
    """Background daemon thread. Calls _tick() each interval and schedules
    proactive spoken briefings when speak_queue is provided."""

    def __init__(
        self,
        interval_minutes: int = 30,
        speak_queue: "_queue_mod.Queue[str] | None" = None,
        proactive_tts: bool = True,
        context_poll_seconds: int = 60,
        idle_fn=None,
    ) -> None:
        from voice import idle as _idle
        self._interval = interval_minutes * 60
        self._context_poll_seconds = max(1, int(context_poll_seconds))
        self._idle_fn = idle_fn if idle_fn is not None else _idle.get_idle_seconds
        self._ticks_since_full = 0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._speak_queue = speak_queue
        self._proactive_tts = proactive_tts

        # Idle-return state machine. _away_since is in-memory only (a restart
        # while away just re-detects on the next poll); the fired timestamp
        # persists so a restart doesn't immediately re-fire the notice.
        self._away_since: datetime | None = None

        # Activity awareness (process-based silence + reactive triggers). All
        # in-memory — a restart just re-baselines on the next poll, same as
        # _away_since. _prev_procs starts empty so the first poll baselines
        # rather than firing "launched" triggers for already-running apps.
        self._prev_procs: set[str] = set()
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
        self._last_idle_return_fired: datetime | None = _parse_dt(state.get("idle_return_fired"))

        # Nudge deduplication (reset each day)
        self._nudged_events: set[str] = set(state.get("nudged", []))
        self._nudge_reset_date: date | None = _parse_date(state.get("nudged_date"))

        # Migrated proactive-check dedup state (Phase 1 of the roadmap migration).
        self._seen_pr_event_ids: list[str] = list(state.get("seen_pr_event_ids", []))
        self._deadline_fired: dict[str, list[str]] = dict(state.get("deadline_fired", {}))
        self._seen_ambient_ids: list[str] = list(state.get("seen_ambient_ids", []))
        self._git_todo_done_date: date | None = _parse_date(state.get("git_todo_date"))
        self._build_watch_done_date: date | None = _parse_date(state.get("build_watch_date"))
        self._last_test_ok: bool | None = state.get("last_test_ok")
        self._last_workflow_conclusion: str | None = state.get("last_workflow_conclusion")
        self._review_reminder_done_date: date | None = _parse_date(state.get("review_reminder_date"))

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
            "nudged": sorted(self._nudged_events),
            "nudged_date": str(self._nudge_reset_date) if self._nudge_reset_date else None,
            "idle_return_fired": self._last_idle_return_fired.isoformat() if self._last_idle_return_fired else None,
            "seen_pr_event_ids": self._seen_pr_event_ids,
            "deadline_fired": self._deadline_fired,
            "seen_ambient_ids": self._seen_ambient_ids,
            "git_todo_date": str(self._git_todo_done_date) if self._git_todo_done_date else None,
            "build_watch_date": str(self._build_watch_done_date) if self._build_watch_done_date else None,
            "last_test_ok": self._last_test_ok,
            "last_workflow_conclusion": self._last_workflow_conclusion,
            "review_reminder_date": str(self._review_reminder_done_date) if self._review_reminder_done_date else None,
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
        if _OUTPUT_SUPPRESSED:
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
                _tick()
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
        Idle-return and the expensive slow tick (calendar/email/deadlines +
        scheduled briefings) stay gated to non-quiet hours, so Vesper still never
        speaks, toasts, or nudges at night."""
        try:
            self._check_activity()
        except Exception as _e:
            print(f"[heartbeat] activity check error: {_e}", flush=True)
        if self._is_quiet():
            return
        try:
            self._check_idle_return()
        except Exception as _e:
            print(f"[heartbeat] idle check error: {_e}", flush=True)
        self._ticks_since_full += 1
        if self._ticks_since_full * self._context_poll_seconds >= self._interval:
            self._ticks_since_full = 0
            _tick()
            self._run_scheduled()

    def _check_idle_return(self) -> None:
        """Away/return state machine, run every fast poll.

        Away: idle >= threshold → record _away_since (back-dated to when
        idleness actually started). Return: fresh input (idle < 5 s) while
        away → fire the notice + context profiles, gated by a persisted
        cooldown so restarts and rapid re-idles don't spam."""
        from voice import config as cfg
        idle_seconds = self._idle_fn()
        if idle_seconds is None:
            return  # signal unavailable this poll
        conf = cfg.load()
        now = datetime.now(cfg.get_timezone())

        threshold_s = float(conf.get("idle_return_threshold_minutes", 20)) * 60
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
            parts = [f"Welcome back — you were away for {mins} minute{'s' if mins != 1 else ''}."]
            unread = _count_unread()
            if unread:
                parts.append(f"{unread} notice{'s' if unread != 1 else ''} waiting.")
            text = " ".join(parts)
            self._speak(text)
            _post(text)

        try:
            self._check_context_profiles(conf, away_duration)
        except Exception as _e:
            print(f"[heartbeat] context profile error: {_e}", flush=True)

    def _check_context_profiles(self, conf: dict, away_duration: timedelta) -> None:
        """Fire profiles with a context/idle_return trigger when a
        return-from-idle event's away duration meets the profile's
        min_idle_minutes. Like the time triggers, calls profiles.activate()
        directly (un-gated — the user configured the trigger themselves).
        Cooldown reuses the profile's own last_fired (minimum 30 min between
        fires), independent of the global notice cooldown."""
        from voice import profiles

        now = datetime.now(timezone.utc)
        for profile_id, profile in profiles.load().items():
            try:
                trig = profile.get("trigger") or {}
                if trig.get("type") != "context" or trig.get("signal") != "idle_return":
                    continue

                min_minutes = float(trig.get("min_idle_minutes",
                                             conf.get("idle_return_threshold_minutes", 20)))
                if away_duration < timedelta(minutes=min_minutes):
                    continue

                fired_dt = _parse_dt(profile.get("last_fired"))
                if fired_dt is not None and now - fired_dt < timedelta(minutes=30):
                    continue  # per-profile cooldown
            except (AttributeError, TypeError, ValueError):
                continue  # malformed profile — skip, don't block later ones

            try:
                result = profiles.activate(profile_id)
                if result.get("launched"):
                    label = result.get("profile", profile_id)
                    text = f"{label} started — launched {', '.join(result['launched'])}."
                    self._speak(text)
                    _post(text)
                if result.get("errors"):
                    _post(f"{profile.get('label', profile_id)}: {'; '.join(result['errors'])}", level="URGENT")
            except Exception as exc:
                print(f"[heartbeat] context profile error for {profile_id}: {exc}", flush=True)

    def _check_activity(self) -> None:
        """One process scan per fast poll, feeding two consumers: the busy-state
        silence gate and the reactive process triggers. Opt-in and dormant until
        activity_awareness_enabled. Fails open (activity.running_processes never
        raises); when disabled we skip entirely and leave _prev_procs stale so a
        later enable re-baselines instead of firing on already-open apps."""
        from voice import activity, config as cfg
        conf = cfg.load()
        if not conf.get("activity_awareness_enabled", False):
            return
        procs = activity.running_processes()
        self._update_busy_state(conf, procs)
        self._check_process_triggers(conf, procs)
        self._prev_procs = procs

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

    def _check_process_triggers(self, conf: dict, procs: set[str]) -> None:
        """Fire profiles with a `process` trigger. `event: "launched"` is
        edge-triggered on a newly-appeared exe (procs - prev), naturally firing
        once per launch; `event: "running"` is level-triggered while the exe is
        present, guarded by the profile's own 30-min last_fired cooldown. Calls
        the shared un-gated profiles.activate() like the time/context triggers."""
        from voice import profiles
        now = datetime.now(timezone.utc)
        newly = (procs - self._prev_procs) if self._prev_procs else set()
        for profile_id, profile in profiles.load().items():
            try:
                trig = profile.get("trigger") or {}
                if trig.get("type") != "process":
                    continue
                exe = (trig.get("exe") or "").lower()
                if not exe:
                    continue
                if trig.get("event", "launched") == "launched":
                    if exe not in newly:
                        continue
                else:  # "running"
                    if exe not in procs:
                        continue
                    fired_dt = _parse_dt(profile.get("last_fired"))
                    if fired_dt is not None and now - fired_dt < timedelta(minutes=30):
                        continue
            except (AttributeError, TypeError, ValueError):
                continue  # malformed profile — skip, don't block later ones
            try:
                result = profiles.activate(profile_id)
                if result.get("launched"):
                    label = result.get("profile", profile_id)
                    text = f"{label} started — launched {', '.join(result['launched'])}."
                    self._speak(text)
                    _post(text)
                if result.get("errors"):
                    _post(f"{profile.get('label', profile_id)}: {'; '.join(result['errors'])}", level="URGENT")
            except Exception as exc:
                print(f"[heartbeat] process trigger error for {profile_id}: {exc}", flush=True)

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

    def _check_ambient_notices(self) -> None:
        """Vault-pattern notifications (dependency gaps, synthesis
        readiness) — migrated from scripts/ambient_notifier.py's Discord
        posting; scan/collect logic is unchanged, dedup id scheme (md5 of
        rule:content) matches the old code exactly."""
        import hashlib
        from voice import config as cfg
        conf = cfg.load()
        if not conf.get("ambient_notifier_enabled", True):
            return
        vault = cfg.get_vault_dir()
        if vault is None:
            return
        try:
            import sys
            sys.path.insert(0, str(_ROOT / "scripts"))
            import ambient_notifier  # type: ignore
            state = ambient_notifier.scan_vault_state(vault)
            notifications = ambient_notifier.collect_notifications(state)
        except Exception as _e:
            print(f"[heartbeat] ambient_notifier error: {_e}", flush=True)
            return

        changed = False
        for note in notifications:
            nid = hashlib.md5(f"{note.get('rule', '')}:{note.get('content', '')}".encode()).hexdigest()
            if nid in self._seen_ambient_ids:
                continue
            _post(note.get("content", ""))
            if nid not in self._seen_ambient_ids:
                self._seen_ambient_ids.append(nid)
            changed = True

        if changed:
            if len(self._seen_ambient_ids) > 200:
                self._seen_ambient_ids = self._seen_ambient_ids[-200:]
            self._save_state()

    def _check_habits(self) -> None:
        """Habit auto-check + late-day nudge (migrated from the old
        heartbeat's habits.auto_check()/should_nudge() calls — habits.py's
        own logic and state files are untouched, only the notify call
        moves from dashboard.notify() to _post())."""
        from voice import config as cfg
        conf = cfg.load()
        if not conf.get("habits_enabled", True):
            return
        if cfg.get_vault_dir() is None:
            return
        try:
            import sys
            sys.path.insert(0, str(_ROOT / ".claude" / "scripts"))
            from core import habits  # type: ignore
            from integrations import github_int  # type: ignore

            snapshot = {"github": {"items": github_int.recent_pushes(days=1)}}
            newly = habits.auto_check(snapshot)
            if newly:
                _post(f"Habits auto-checked: {', '.join(newly)}")

            if habits.should_nudge():
                unchecked = habits.unchecked_pillars()
                if unchecked:
                    _title, body = habits.nudge_message(unchecked)
                    _post(body)
                    habits.mark_nudged()
        except Exception as _e:
            print(f"[heartbeat] habits error: {_e}", flush=True)

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

    def _check_spaced_repetition(self) -> None:
        """Once-daily reminder of due spaced-repetition cards. The actual
        review conversation happens via the review_cards/grade_card voice
        tools — this just prompts the user to start one."""
        from voice import config as cfg
        conf = cfg.load()
        if not conf.get("spaced_repetition_enabled", True):
            return

        now = datetime.now(cfg.get_timezone())
        today = now.date()
        if self._review_reminder_done_date == today:
            return
        rh, rm = (int(x) for x in conf.get("review_reminder_time", "10:00").split(":"))
        if now.hour < rh or (now.hour == rh and now.minute < rm):
            return

        self._review_reminder_done_date = today
        self._save_state()

        due = spaced_repetition.due_cards()
        if due:
            n = len(due)
            _post(f"{n} flashcard{'s' if n != 1 else ''} due for review. Say \"quiz me\" to start.")

    def _process_inbox(self) -> None:
        """Classify/summarise new inbox files, promote extracted deadlines,
        refresh the daily-log timeline (migrated from the old heartbeat's
        top-of-tick inbox step — inbox.py's logic is unchanged; only the
        notify call for each summary is new)."""
        process_inbox_once()

    def _check_downloads(self) -> None:
        """Suggest filing new Downloads files into the inbox. Never moves —
        the move happens only via the /cmd/downloads/file endpoint on approval."""
        from voice import config as cfg
        from voice import downloads
        conf = cfg.load()
        if not conf.get("downloads_triage_enabled", False):
            return
        if cfg.get_vault_dir() is None:
            return                       # nowhere to file to
        try:
            folders = conf.get("downloads_watch_folders") or downloads.default_folders()
            exts = conf.get("downloads_watch_exts", downloads.DEFAULT_EXTS)
            data_dir = cfg.get_data_dir()
            seen = downloads.load_seen(data_dir)
            for cand in downloads.scan_new(folders, exts, seen):
                _post(
                    f"You downloaded {cand['name']} — file it into the inbox?",
                    level="INFO",
                    meta={"kind": "download_suggestion", "path": cand["path"],
                          "name": cand["name"]},
                )
                downloads.mark_seen(data_dir, cand["path"], cand["mtime"])
        except Exception as _e:
            print(f"[heartbeat] downloads triage error: {_e}", flush=True)

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
        become nogcal: rows in DEADLINES.md, so threshold alerts cover them."""
        from voice import config as cfg
        from voice import deadlines
        conf = cfg.load()
        if not conf.get("deadline_import_enabled", True):
            return
        days = int(conf.get("deadline_import_lookahead_days", 30))
        events = _fetch_events(days=days, max_results=100)
        added = deadlines.import_from_events(events, conf.get("deadline_import_keywords"))
        if added:
            _post(("Deadlines from calendar: " + "; ".join(added))[:160])

    def _run_scheduled(self) -> None:
        for task in (self._process_inbox, self._check_downloads,
                     self._check_job_alerts,
                     self._morning_briefing, self._evening_wrap,
                     self._check_nudges, self._check_profile_triggers,
                     self._check_calendar_sync, self._check_github_digest,
                     self._check_deadline_import,
                     self._check_deadline_thresholds, self._check_ambient_notices,
                     self._check_habits, self._check_git_todo_summary,
                     self._check_build_watch, self._check_spaced_repetition):
            try:
                task()
            except Exception as _e:
                print(f"[heartbeat] {task.__name__} error: {_e}", flush=True)

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
        events = _fetch_events(days=1, max_results=5)
        if events:
            strs = []
            for e in events[:3]:
                t = e.get("start", "")[11:16] if "T" in e.get("start", "") else "all day"
                strs.append(f"{e.get('summary', '(no title)')} at {t}")
            parts.append(f"Today: {', '.join(strs)}.")
        else:
            parts.append("No events today.")

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
        if tmr:
            t = tmr[0].get("start", "")[11:16] if "T" in tmr[0].get("start", "") else "all day"
            parts.append(f"Tomorrow starts with {tmr[0].get('summary', '(no title)')} at {t}.")
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
                        f"{mins} minute{'s' if mins != 1 else ''}."
                    )
                    self._speak(text)
                    _post(text, level="URGENT")
            except Exception:
                continue

    def _check_profile_triggers(self) -> None:
        """Auto-fire any profile whose `time` trigger is due today. Calls
        profiles.activate() directly — never dispatch()/safety.py — so this
        path is un-gated (the user configured the schedule themselves; a
        voice-triggered activation of the same profile still goes through
        normal confirmation gating via the activate_profile tool)."""
        from voice import config as cfg, profiles

        now = datetime.now(cfg.get_timezone())
        today = now.date()
        weekday = now.strftime("%a").lower()

        for profile_id, profile in profiles.load().items():
            trig = profile.get("trigger") or {}
            if trig.get("type") != "time":
                continue  # "context" triggers reserved, not implemented

            days = trig.get("days") or ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
            if weekday not in days:
                continue

            last_fired = profile.get("last_fired")
            if last_fired and last_fired[:10] == str(today):
                continue  # already fired today

            try:
                th, tm = (int(x) for x in trig.get("time", "00:00").split(":"))
            except ValueError:
                continue

            if now.hour > th or (now.hour == th and now.minute >= tm):
                try:
                    result = profiles.activate(profile_id)
                    if result.get("launched"):
                        label = result.get("profile", profile_id)
                        text = f"{label} started — launched {', '.join(result['launched'])}."
                        self._speak(text)
                        _post(text)
                    if result.get("errors"):
                        _post(f"{profile.get('label', profile_id)}: {'; '.join(result['errors'])}", level="URGENT")
                except Exception as exc:
                    print(f"[heartbeat] profile trigger error for {profile_id}: {exc}", flush=True)

    @staticmethod
    def _is_quiet() -> bool:
        try:
            from voice import config as cfg
            return cfg.is_quiet_hours()
        except Exception:
            return False
