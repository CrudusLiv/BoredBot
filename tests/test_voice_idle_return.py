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

def test_context_poll_seconds_clamped(env):
    hb = Heartbeat(interval_minutes=30, context_poll_seconds=0, idle_fn=lambda: None)
    assert hb._context_poll_seconds == 1


# --- sleep/wake wall-clock gap (idle signal freezes across suspend) ---

def test_large_poll_gap_sets_away_since_even_with_fresh_idle(env):
    """A poll-to-poll wall-clock gap >= threshold (system was asleep) must
    register as away even though the tick-based idle signal reads ~0 right
    after wake -- this is the scenario the GetTickCount freeze misses."""
    hb = make_hb([2.0])
    before = datetime.now(cfg.get_timezone())
    hb._check_idle_return(poll_gap_s=1300.0)  # asleep for ~21.7 min
    after = datetime.now(cfg.get_timezone())
    assert len(env) == 1
    assert env[0].startswith("Welcome back — you were away for ")
    assert hb._away_since is None
    # away_duration reflects the sleep gap, not the near-zero idle signal
    assert before - timedelta(seconds=1301) <= hb._last_idle_return_fired <= after


def test_small_poll_gap_does_not_trigger_away(env):
    hb = make_hb([2.0])
    hb._check_idle_return(poll_gap_s=45.0)  # normal poll cadence
    assert hb._away_since is None
    assert env == []


def test_poll_gap_keeps_earlier_idle_based_away_since(env):
    """If idle-based tracking already back-dated away_since further than the
    gap start, keep the more accurate (earlier) timestamp instead of
    overwriting it with the later gap-derived one."""
    hb = make_hb([1300.0, 1400.0])
    hb._check_idle_return(poll_gap_s=0.0)  # sets away_since via idle path
    earlier = hb._away_since
    hb._check_idle_return(poll_gap_s=1300.0)  # gap starts later than `earlier`
    assert hb._away_since == earlier


def test_speak_pushed_on_return(env):
    import queue
    q: "queue.Queue[str]" = queue.Queue()
    seq = iter([1300.0, 2.0])
    hb = Heartbeat(interval_minutes=30, speak_queue=q, proactive_tts=True,
                   idle_fn=lambda: next(seq))
    drain(hb, 2)
    assert q.get_nowait().startswith("Welcome back")
