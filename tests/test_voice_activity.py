"""Tests for process-based activity awareness.

Two layers:
  1. voice/activity.py — the fail-open process sensor (psutil monkeypatched).
  2. voice/heartbeat.py — the busy-state silence gate + reactive process
     triggers, driven by injecting scripted process sets (no real OS scan).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from voice import config as cfg
from voice import heartbeat as hb_mod
from voice.heartbeat import Heartbeat


# --------------------------------------------------------------------------
# 1. Sensor — voice/activity.py
# --------------------------------------------------------------------------

class _FakeProc:
    def __init__(self, name):
        self.info = {"name": name}


class _BadProc:
    @property
    def info(self):
        raise RuntimeError("process vanished mid-iteration")


def test_running_processes_lowercases(monkeypatch):
    import psutil
    from voice import activity
    monkeypatch.setattr(psutil, "process_iter",
                        lambda attrs=None: [_FakeProc("Code.EXE"), _FakeProc("zoom.exe")])
    assert activity.running_processes() == {"code.exe", "zoom.exe"}


def test_running_processes_fails_open_on_error(monkeypatch):
    import psutil
    from voice import activity

    def _boom(attrs=None):
        raise RuntimeError("psutil down")

    monkeypatch.setattr(psutil, "process_iter", _boom)
    assert activity.running_processes() == set()


def test_running_processes_skips_bad_entries(monkeypatch):
    import psutil
    from voice import activity
    monkeypatch.setattr(psutil, "process_iter",
                        lambda attrs=None: [_FakeProc("a.exe"), _BadProc(), _FakeProc(None)])
    assert activity.running_processes() == {"a.exe"}


def test_matched_case_insensitive():
    from voice import activity
    assert activity.matched({"game.exe", "code.exe"}, ["Game.EXE"]) == {"game.exe"}


def test_matched_empty_inputs():
    from voice import activity
    assert activity.matched(set(), ["a.exe"]) == set()
    assert activity.matched({"a.exe"}, []) == set()


# --------------------------------------------------------------------------
# 2. Heartbeat integration
# --------------------------------------------------------------------------

CONF = {
    "timezone_offset_hours": 8,
    "activity_awareness_enabled": True,
    "silence_when_running": ["game.exe"],
    # start == end => is_quiet_hours() is always False, so busy-digest tests are
    # deterministic regardless of wall-clock. Quiet-hours behaviour is covered
    # explicitly by test_poll_runs_activity_but_skips_idle_during_quiet.
    "quiet_hours_start": "00:00",
    "quiet_hours_end": "00:00",
}


@pytest.fixture(autouse=True)
def _reset_suppression():
    """Suppression is a module global — reset around every test so state never
    leaks between tests."""
    hb_mod._set_output_suppressed(False)
    yield
    hb_mod._set_output_suppressed(False)


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Isolated data dir + activity config + captured _post output + speak queue."""
    import queue
    monkeypatch.setattr(cfg, "get_data_dir", lambda: tmp_path)
    monkeypatch.setattr(cfg, "load", lambda: dict(CONF))
    posts: list[str] = []
    monkeypatch.setattr(hb_mod, "_post", lambda text, level="INFO": posts.append(text))
    q: "queue.Queue[str]" = queue.Queue()
    return posts, q, tmp_path


def _drive(monkeypatch, hb, proc_sets):
    """Feed successive process-name sets through _check_activity."""
    from voice import activity
    seq = iter(proc_sets)
    monkeypatch.setattr(activity, "running_processes", lambda: next(seq))
    for _ in proc_sets:
        hb._check_activity()


def _mk(env, **kw):
    _, q, _ = env
    return Heartbeat(interval_minutes=30, speak_queue=q, proactive_tts=True,
                     idle_fn=lambda: 1.0, **kw)


# --- busy state (silence + digest) ---

def test_enters_busy_and_suppresses(env, monkeypatch):
    hb = _mk(env)
    _drive(monkeypatch, hb, [{"game.exe"}])
    assert hb._busy is True
    assert hb._busy_proc == "game.exe"
    assert hb_mod._output_suppressed() is True


def test_speak_held_while_busy(env, monkeypatch):
    posts, q, _ = env
    hb = _mk(env)
    _drive(monkeypatch, hb, [{"game.exe"}])
    hb._speak("proactive line")
    assert q.empty()  # suppressed


def test_exit_busy_delivers_digest_with_unread(env, monkeypatch):
    posts, q, tmp_path = env
    (tmp_path / "voice_notices.jsonl").write_text(
        '{"id": "x", "text": "t", "level": "INFO", "read": false}\n', encoding="utf-8"
    )
    hb = _mk(env)
    _drive(monkeypatch, hb, [{"game.exe"}, set()])
    assert hb._busy is False
    assert hb_mod._output_suppressed() is False
    assert any(p.startswith("You're back from game.exe") and "1 notice waiting" in p for p in posts)


def test_exit_busy_silent_when_no_unread(env, monkeypatch):
    posts, q, _ = env
    hb = _mk(env)
    _drive(monkeypatch, hb, [{"game.exe"}, set()])
    assert hb._busy is False
    assert posts == []  # nothing accrued → no digest


def test_disabled_never_enters_busy(env, monkeypatch):
    monkeypatch.setattr(cfg, "load", lambda: dict(CONF, activity_awareness_enabled=False))
    hb = _mk(env)
    _drive(monkeypatch, hb, [{"game.exe"}])
    assert hb._busy is False
    assert hb_mod._output_suppressed() is False


def test_still_busy_tracks_surviving_process(env, monkeypatch):
    monkeypatch.setattr(cfg, "load", lambda: dict(CONF, silence_when_running=["game.exe", "zoom.exe"]))
    hb = _mk(env)
    _drive(monkeypatch, hb, [{"game.exe", "zoom.exe"}, {"zoom.exe"}])
    assert hb._busy is True
    assert hb._busy_proc == "zoom.exe"


# --- _post tray suppression (real _post, not the env mock) ---

def test_post_skips_tray_when_suppressed(tmp_path, monkeypatch):
    from voice import tray, ui_server
    monkeypatch.setattr(cfg, "get_data_dir", lambda: tmp_path)
    monkeypatch.setattr(cfg, "load", lambda: dict(CONF))
    toasts: list[str] = []
    monkeypatch.setattr(tray, "notify", lambda title, text: toasts.append(text))
    monkeypatch.setattr(ui_server, "post_event", lambda ev: None)

    hb_mod._set_output_suppressed(True)
    hb_mod._post("held")
    assert toasts == []  # tray toast suppressed
    # but still written to the jsonl log
    assert "held" in (tmp_path / "voice_notices.jsonl").read_text(encoding="utf-8")

    hb_mod._set_output_suppressed(False)
    hb_mod._post("live")
    assert toasts == ["live"]


# --- live busy-state broadcast to the orb UI ---

def test_busy_state_broadcasts_ws_event(env, monkeypatch):
    """Entering/leaving busy must emit a busy_state event over the WS so the orb
    can show a live 'silenced' indicator (the state is otherwise invisible)."""
    from voice import ui_server
    events: list[dict] = []
    monkeypatch.setattr(ui_server, "post_event", lambda ev: events.append(ev))
    hb = _mk(env)
    _drive(monkeypatch, hb, [{"game.exe"}, set()])
    busy = [e for e in events if e.get("type") == "busy_state"]
    assert {"type": "busy_state", "busy": True, "proc": "game.exe"} in busy
    assert any(e["busy"] is False for e in busy)


def test_no_busy_broadcast_without_transition(env, monkeypatch):
    """Staying busy across polls must not re-broadcast enter each time — only
    state transitions emit (a surviving-proc change is the one allowed update)."""
    monkeypatch.setattr(cfg, "load", lambda: dict(CONF, silence_when_running=["game.exe"]))
    from voice import ui_server
    events: list[dict] = []
    monkeypatch.setattr(ui_server, "post_event", lambda ev: events.append(ev))
    hb = _mk(env)
    _drive(monkeypatch, hb, [{"game.exe"}, {"game.exe"}])
    enters = [e for e in events if e.get("type") == "busy_state" and e["busy"] is True]
    assert len(enters) == 1


# --- quiet-hours: activity runs 24/7, idle/slow-tick stay gated ---

def test_poll_runs_activity_but_skips_idle_during_quiet(env, monkeypatch):
    """During quiet hours _poll_once must still run the activity check (so the
    busy gate + live indicator work at night) but must NOT run idle-return (no
    proactive night speech)."""
    monkeypatch.setattr(cfg, "load",
                        lambda: dict(CONF, quiet_hours_start="00:00", quiet_hours_end="23:59"))
    from voice import activity, ui_server
    events: list[dict] = []
    monkeypatch.setattr(ui_server, "post_event", lambda ev: events.append(ev))
    monkeypatch.setattr(activity, "running_processes", lambda: {"game.exe"})
    hb = _mk(env)
    idle_calls: list[int] = []
    monkeypatch.setattr(hb, "_check_idle_return", lambda: idle_calls.append(1))
    hb._poll_once()
    assert hb._busy is True  # activity check ran despite quiet hours
    assert any(e.get("type") == "busy_state" and e["busy"] for e in events)
    assert idle_calls == []   # idle-return held during quiet hours


# --- reactive process triggers ---

def _proc_profile(exe="game.exe", event="launched", last_fired=None):
    return {
        "label": "Game Mode",
        "apps": ["discord"],
        "trigger": {"type": "process", "exe": exe, "event": event},
        "created_at": "2026-07-01T00:00:00+00:00",
        "last_fired": last_fired,
    }


@pytest.fixture
def proc_env(env, monkeypatch):
    from voice import profiles
    store: dict[str, dict] = {}
    activations: list[str] = []
    monkeypatch.setattr(profiles, "load", lambda: store)
    monkeypatch.setattr(
        profiles, "activate",
        lambda pid: (activations.append(pid),
                     {"profile": store[pid]["label"], "launched": ["discord"], "errors": []})[1],
    )
    return env, activations, store


def test_launched_fires_on_appearance(proc_env, monkeypatch):
    (posts, q, _), activations, store = proc_env
    store["game"] = _proc_profile(event="launched")
    hb = _mk(proc_env[0])
    # poll1 baselines (prev empty), poll2 sees game.exe newly appear
    _drive(monkeypatch, hb, [{"other.exe"}, {"other.exe", "game.exe"}])
    assert activations == ["game"]


def test_launched_baseline_no_fire_first_poll(proc_env, monkeypatch):
    (posts, q, _), activations, store = proc_env
    store["game"] = _proc_profile(event="launched")
    hb = _mk(proc_env[0])
    _drive(monkeypatch, hb, [{"game.exe"}])  # already running at first scan
    assert activations == []  # baseline, not a launch event


def test_launched_not_refired_while_running(proc_env, monkeypatch):
    (posts, q, _), activations, store = proc_env
    store["game"] = _proc_profile(event="launched")
    hb = _mk(proc_env[0])
    _drive(monkeypatch, hb, [{"other.exe"}, {"other.exe", "game.exe"}, {"other.exe", "game.exe"}])
    assert activations == ["game"]  # fired once, not again while still open


def test_running_fires_while_present(proc_env, monkeypatch):
    (posts, q, _), activations, store = proc_env
    store["game"] = _proc_profile(event="running")
    hb = _mk(proc_env[0])
    _drive(monkeypatch, hb, [{"game.exe"}])
    assert activations == ["game"]


def test_running_respects_cooldown(proc_env, monkeypatch):
    (posts, q, _), activations, store = proc_env
    recent = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    store["game"] = _proc_profile(event="running", last_fired=recent)
    hb = _mk(proc_env[0])
    _drive(monkeypatch, hb, [{"game.exe"}])
    assert activations == []  # 10 min < 30-min cooldown


def test_time_trigger_ignored_by_process_check(proc_env, monkeypatch):
    (posts, q, _), activations, store = proc_env
    store["evening"] = {
        "label": "Evening", "apps": ["spotify"],
        "trigger": {"type": "time", "time": "18:00"},
        "created_at": "2026-07-01T00:00:00+00:00", "last_fired": None,
    }
    hb = _mk(proc_env[0])
    _drive(monkeypatch, hb, [{"other.exe"}, {"other.exe", "vesper.exe"}])
    assert activations == []
