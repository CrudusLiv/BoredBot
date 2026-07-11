"""Tests for the idle-return state machine in voice/heartbeat.py.

Drives Heartbeat._check_idle_return() with an injected fake idle_fn returning
scripted idle-second sequences — no real OS idle time, no threads."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from voice import config as cfg
from voice import heartbeat as hb_mod
from voice.heartbeat import Heartbeat

CONF = {
    "timezone_offset_hours": 8,
    "idle_return_enabled": True,
    "idle_return_threshold_minutes": 20,
    "idle_return_cooldown_minutes": 15,
    # start == end => is_quiet_hours() always False, so the slow-tick cadence
    # tests are deterministic now that _poll_once gates idle-return + slow tick
    # behind quiet hours.
    "quiet_hours_start": "00:00",
    "quiet_hours_end": "00:00",
}


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Isolated data dir + fixed config + captured _post output."""
    monkeypatch.setattr(cfg, "get_data_dir", lambda: tmp_path)
    monkeypatch.setattr(cfg, "load", lambda: dict(CONF))
    posts: list[str] = []
    monkeypatch.setattr(hb_mod, "_post", lambda text, level="INFO": posts.append(text))
    return posts


def make_hb(idle_values) -> Heartbeat:
    seq = iter(idle_values)
    return Heartbeat(interval_minutes=30, idle_fn=lambda: next(seq))


def drain(hb: Heartbeat, n: int) -> None:
    for _ in range(n):
        hb._check_idle_return()


# --- away/return state machine ---

def test_below_threshold_does_nothing(env):
    hb = make_hb([60.0])
    drain(hb, 1)
    assert hb._away_since is None
    assert env == []


def test_crossing_threshold_sets_backdated_away_since(env):
    hb = make_hb([1300.0])  # > 20 min threshold (1200 s)
    before = datetime.now(cfg.get_timezone())
    drain(hb, 1)
    after = datetime.now(cfg.get_timezone())
    assert hb._away_since is not None
    # back-dated to when idleness actually started
    assert before - timedelta(seconds=1301) <= hb._away_since <= after - timedelta(seconds=1299)


def test_return_fires_notice_once(env):
    hb = make_hb([1300.0, 2.0])
    drain(hb, 2)
    assert len(env) == 1
    assert env[0].startswith("Welcome back — you were away for ")
    assert hb._away_since is None
    assert hb._last_idle_return_fired is not None


def test_notice_includes_unread_count(env, tmp_path):
    (tmp_path / "voice_notices.jsonl").write_text(
        '{"id": "x", "text": "t", "level": "INFO", "read": false}\n', encoding="utf-8"
    )
    hb = make_hb([1300.0, 2.0])
    drain(hb, 2)
    assert "1 notice waiting" in env[0]


def test_no_unread_omits_notice_sentence(env):
    hb = make_hb([1300.0, 2.0])
    drain(hb, 2)
    assert "waiting" not in env[0]


def test_intermediate_idle_keeps_away_state(env):
    """Input 30s ago is neither 'still away' nor a fresh return (<5s) —
    the away state persists until a fresh-input poll."""
    hb = make_hb([1300.0, 30.0, 2.0])
    drain(hb, 3)
    assert len(env) == 1  # exactly one fire, on the <5s poll


def test_cooldown_blocks_refire(env):
    hb = make_hb([1300.0, 2.0, 1300.0, 2.0])
    drain(hb, 4)
    assert len(env) == 1  # second return is within the 15-min cooldown


def test_cooldown_elapsed_allows_refire(env):
    hb = make_hb([1300.0, 2.0, 1300.0, 2.0])
    drain(hb, 2)
    # simulate the cooldown having elapsed
    hb._last_idle_return_fired = datetime.now(cfg.get_timezone()) - timedelta(minutes=16)
    drain(hb, 2)
    assert len(env) == 2


def test_none_signal_skips_poll(env):
    hb = make_hb([None, None])
    drain(hb, 2)
    assert hb._away_since is None
    assert env == []


def test_none_mid_away_preserves_state(env):
    hb = make_hb([1300.0, None, 2.0])
    drain(hb, 3)
    assert len(env) == 1


def test_disabled_suppresses_notice_but_still_records_fire(env, monkeypatch):
    conf = dict(CONF, idle_return_enabled=False)
    monkeypatch.setattr(cfg, "load", lambda: conf)
    hb = make_hb([1300.0, 2.0])
    drain(hb, 2)
    assert env == []
    assert hb._last_idle_return_fired is not None


def test_fired_timestamp_persists_across_restart(env):
    hb = make_hb([1300.0, 2.0])
    drain(hb, 2)
    hb2 = make_hb([])
    assert hb2._last_idle_return_fired is not None
    assert abs((hb2._last_idle_return_fired - hb._last_idle_return_fired).total_seconds()) < 1


# --- fast-poll cadence ---

def test_full_tick_runs_only_when_interval_elapsed(env, monkeypatch):
    hb = make_hb([1.0] * 100)  # active user; idle check is a no-op
    ticks: list[int] = []
    monkeypatch.setattr(hb_mod, "_tick", lambda: ticks.append(1))
    monkeypatch.setattr(hb, "_run_scheduled", lambda: None)
    # 30-min interval at 60 s polls → full tick on the 30th poll, not before
    for _ in range(29):
        hb._poll_once()
    assert ticks == []
    hb._poll_once()
    assert ticks == [1]
    assert hb._ticks_since_full == 0


def test_idle_check_error_does_not_starve_slow_tick(env, monkeypatch):
    def _boom():
        raise RuntimeError("boom")

    hb = Heartbeat(interval_minutes=30, idle_fn=_boom)
    ticks: list[int] = []
    monkeypatch.setattr(hb_mod, "_tick", lambda: ticks.append(1))
    monkeypatch.setattr(hb, "_run_scheduled", lambda: None)
    for _ in range(29):
        hb._poll_once()
    assert ticks == []
    hb._poll_once()
    assert ticks == [1]


def test_context_poll_seconds_clamped(env):
    hb = Heartbeat(interval_minutes=30, context_poll_seconds=0, idle_fn=lambda: None)
    assert hb._context_poll_seconds == 1


def test_speak_pushed_on_return(env):
    import queue
    q: "queue.Queue[str]" = queue.Queue()
    seq = iter([1300.0, 2.0])
    hb = Heartbeat(interval_minutes=30, speak_queue=q, proactive_tts=True,
                   idle_fn=lambda: next(seq))
    drain(hb, 2)
    assert q.get_nowait().startswith("Welcome back")


# --- profile context triggers ---

def _context_profile(min_idle=20, last_fired=None):
    return {
        "label": "Study Mode",
        "apps": ["vscode"],
        "trigger": {"type": "context", "signal": "idle_return", "min_idle_minutes": min_idle},
        "created_at": "2026-07-01T00:00:00+00:00",
        "last_fired": last_fired,
    }


@pytest.fixture
def profile_env(env, monkeypatch):
    """env + fake profile store; returns (posts, activations, store)."""
    from voice import profiles
    store: dict[str, dict] = {}
    activations: list[str] = []
    monkeypatch.setattr(profiles, "load", lambda: store)
    monkeypatch.setattr(
        profiles, "activate",
        lambda pid: (activations.append(pid),
                     {"profile": store[pid]["label"], "launched": ["code"], "errors": []})[1],
    )
    return env, activations, store


def test_context_profile_fires_on_return(profile_env):
    posts, activations, store = profile_env
    store["study"] = _context_profile(min_idle=20)
    hb = make_hb([1300.0, 2.0])
    drain(hb, 2)
    assert activations == ["study"]
    assert any("Study Mode started" in p for p in posts)


def test_context_profile_below_min_idle_skipped(profile_env):
    posts, activations, store = profile_env
    store["study"] = _context_profile(min_idle=30)  # away was only ~21-22 min
    hb = make_hb([1300.0, 2.0])
    drain(hb, 2)
    assert activations == []


def test_context_profile_own_cooldown(profile_env):
    from datetime import timezone as _tz
    posts, activations, store = profile_env
    recent = datetime.now(_tz.utc) - timedelta(minutes=10)
    store["study"] = _context_profile(min_idle=20, last_fired=recent.isoformat())
    hb = make_hb([1300.0, 2.0])
    drain(hb, 2)
    assert activations == []  # fired 10 min ago < 30-min minimum


def test_context_profile_cooldown_elapsed_fires(profile_env):
    from datetime import timezone as _tz
    posts, activations, store = profile_env
    old = datetime.now(_tz.utc) - timedelta(minutes=45)
    store["study"] = _context_profile(min_idle=20, last_fired=old.isoformat())
    hb = make_hb([1300.0, 2.0])
    drain(hb, 2)
    assert activations == ["study"]


def test_time_trigger_profiles_ignored_by_context_check(profile_env):
    posts, activations, store = profile_env
    store["evening"] = {
        "label": "Evening", "apps": ["spotify"],
        "trigger": {"type": "time", "time": "18:00"},
        "created_at": "2026-07-01T00:00:00+00:00", "last_fired": None,
    }
    hb = make_hb([1300.0, 2.0])
    drain(hb, 2)
    assert activations == []


def test_min_idle_defaults_to_global_threshold(profile_env):
    posts, activations, store = profile_env
    prof = _context_profile()
    del prof["trigger"]["min_idle_minutes"]
    store["study"] = prof
    hb = make_hb([1300.0, 2.0])  # away ~21.7 min >= default 20
    drain(hb, 2)
    assert activations == ["study"]


def test_context_profiles_fire_even_when_notice_disabled(profile_env, monkeypatch):
    posts, activations, store = profile_env
    monkeypatch.setattr(cfg, "load", lambda: dict(CONF, idle_return_enabled=False))
    store["study"] = _context_profile(min_idle=20)
    hb = make_hb([1300.0, 2.0])
    drain(hb, 2)
    assert activations == ["study"]
    assert not any(p.startswith("Welcome back") for p in posts)


def test_activation_error_does_not_break_return_event(profile_env, monkeypatch):
    from voice import profiles
    posts, activations, store = profile_env
    store["study"] = _context_profile(min_idle=20)

    def _boom(pid):
        raise RuntimeError("launch failed")

    monkeypatch.setattr(profiles, "activate", _boom)
    hb = make_hb([1300.0, 2.0])
    drain(hb, 2)  # must not raise
    assert hb._last_idle_return_fired is not None


def test_malformed_profile_does_not_block_later_ones(profile_env):
    posts, activations, store = profile_env
    # Insertion order is iteration order — the malformed profile is processed
    # first. Its explicit-None min_idle_minutes makes float(trig.get(...))
    # raise TypeError (dict.get returns the stored None, not the default).
    store["bad"] = {
        "label": "Bad", "apps": [],
        "trigger": {"type": "context", "signal": "idle_return", "min_idle_minutes": None},
        "last_fired": None,
    }
    store["study"] = _context_profile(min_idle=20)
    hb = make_hb([1300.0, 2.0])
    drain(hb, 2)  # must not raise, and must not skip the valid profile
    assert activations == ["study"]
