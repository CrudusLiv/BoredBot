"""voice/heartbeat.py::_check_power_transition -- speak once when the
laptop moves onto or off AC power, mirroring the idle-return trigger."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from voice import config as cfg
from voice import heartbeat as hb_mod
from voice.heartbeat import Heartbeat

TZ8 = timezone(timedelta(hours=8))
CONF = {"power_trigger_enabled": True, "power_trigger_cooldown_seconds": 45}


def _env(tmp_path, monkeypatch, conf=None, now=None):
    monkeypatch.setattr(cfg, "get_data_dir", lambda: tmp_path)
    monkeypatch.setattr(cfg, "load", lambda: dict(conf or CONF))
    monkeypatch.setattr(cfg, "get_timezone", lambda: TZ8)
    fixed_now = now or datetime(2026, 7, 7, 12, 0, tzinfo=TZ8)
    monkeypatch.setattr(hb_mod, "datetime", type("F", (), {
        "now": staticmethod(lambda tz=None: fixed_now),
        "fromisoformat": staticmethod(datetime.fromisoformat),
    }))
    posts = []
    monkeypatch.setattr(hb_mod, "_post",
                        lambda text, level="INFO", meta=None: posts.append(text))
    return posts


def _hb(tmp_path, monkeypatch, spoken, status):
    box = {"v": status}
    hb = Heartbeat(interval_minutes=30, idle_fn=lambda: None,
                   power_fn=lambda: box["v"])
    monkeypatch.setattr(hb, "_speak", lambda text: spoken.append(text))
    return hb, box


def test_first_observation_is_silent(tmp_path, monkeypatch):
    posts = _env(tmp_path, monkeypatch)
    spoken = []
    hb, _ = _hb(tmp_path, monkeypatch, spoken, {"on_ac": True, "percent": 90})
    hb._check_power_transition()
    assert spoken == []
    assert posts == []
    assert hb._last_on_ac is True


def test_unplug_speaks_and_posts_with_percent(tmp_path, monkeypatch):
    posts = _env(tmp_path, monkeypatch)
    spoken = []
    hb, box = _hb(tmp_path, monkeypatch, spoken, {"on_ac": True, "percent": 90})
    hb._last_on_ac = True
    box["v"] = {"on_ac": False, "percent": 84}
    hb._check_power_transition()
    assert len(spoken) == 1
    assert "84%" in spoken[0]
    assert len(posts) == 1
    assert hb._last_on_ac is False
    assert hb._last_power_fired == datetime(2026, 7, 7, 12, 0, tzinfo=TZ8)


def test_plug_speaks_with_percent(tmp_path, monkeypatch):
    posts = _env(tmp_path, monkeypatch)
    spoken = []
    hb, box = _hb(tmp_path, monkeypatch, spoken, {"on_ac": False, "percent": 30})
    hb._last_on_ac = False
    box["v"] = {"on_ac": True, "percent": 31}
    hb._check_power_transition()
    assert len(spoken) == 1
    assert "31%" in spoken[0]
    assert hb._last_on_ac is True


def test_no_change_is_silent(tmp_path, monkeypatch):
    posts = _env(tmp_path, monkeypatch)
    spoken = []
    hb, _ = _hb(tmp_path, monkeypatch, spoken, {"on_ac": True, "percent": 50})
    hb._last_on_ac = True
    hb._check_power_transition()
    assert spoken == []
    assert posts == []


def test_none_status_is_silent(tmp_path, monkeypatch):
    posts = _env(tmp_path, monkeypatch)
    spoken = []
    hb, box = _hb(tmp_path, monkeypatch, spoken, None)
    hb._last_on_ac = True
    hb._check_power_transition()
    assert spoken == []
    assert posts == []
    assert hb._last_on_ac is True


def test_unknown_ac_is_silent(tmp_path, monkeypatch):
    posts = _env(tmp_path, monkeypatch)
    spoken = []
    hb, _ = _hb(tmp_path, monkeypatch, spoken, {"on_ac": None, "percent": 50})
    hb._last_on_ac = True
    hb._check_power_transition()
    assert spoken == []
    assert posts == []


def test_disabled_is_silent(tmp_path, monkeypatch):
    posts = _env(tmp_path, monkeypatch,
                 dict(CONF, power_trigger_enabled=False))
    spoken = []
    hb, box = _hb(tmp_path, monkeypatch, spoken, {"on_ac": True, "percent": 80})
    hb._last_on_ac = True
    box["v"] = {"on_ac": False, "percent": 80}
    hb._check_power_transition()
    assert spoken == []
    assert posts == []


def test_cooldown_suppresses_second_transition(tmp_path, monkeypatch):
    posts = _env(tmp_path, monkeypatch,
                 now=datetime(2026, 7, 7, 12, 0, 30, tzinfo=TZ8))
    spoken = []
    hb, box = _hb(tmp_path, monkeypatch, spoken, {"on_ac": False, "percent": 40})
    hb._last_on_ac = False
    hb._last_power_fired = datetime(2026, 7, 7, 12, 0, 0, tzinfo=TZ8)
    box["v"] = {"on_ac": True, "percent": 40}
    hb._check_power_transition()
    assert spoken == []
    assert posts == []
    # A suppressed edge does not advance _last_on_ac -- the final resting
    # state gets announced once the flapping settles.
    assert hb._last_on_ac is False


def test_transition_after_cooldown_fires(tmp_path, monkeypatch):
    posts = _env(tmp_path, monkeypatch,
                 now=datetime(2026, 7, 7, 12, 1, 0, tzinfo=TZ8))
    spoken = []
    hb, box = _hb(tmp_path, monkeypatch, spoken, {"on_ac": False, "percent": 40})
    hb._last_on_ac = False
    hb._last_power_fired = datetime(2026, 7, 7, 12, 0, 0, tzinfo=TZ8)
    box["v"] = {"on_ac": True, "percent": 40}
    hb._check_power_transition()
    assert len(spoken) == 1
    assert hb._last_on_ac is True


def test_percent_none_uses_fallback_line(tmp_path, monkeypatch):
    posts = _env(tmp_path, monkeypatch)
    spoken = []
    hb, box = _hb(tmp_path, monkeypatch, spoken, {"on_ac": True, "percent": 50})
    hb._last_on_ac = True
    box["v"] = {"on_ac": False, "percent": None}
    hb._check_power_transition()
    assert len(spoken) == 1
    assert "None" not in spoken[0]
    assert "%" not in spoken[0]


def test_power_fired_state_round_trips(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "get_data_dir", lambda: tmp_path)
    hb = Heartbeat(interval_minutes=30, idle_fn=lambda: None)
    assert hb._last_power_fired is None
    hb._last_power_fired = datetime(2026, 7, 7, 12, 0, tzinfo=TZ8)
    hb._save_state()
    hb2 = Heartbeat(interval_minutes=30, idle_fn=lambda: None)
    assert hb2._last_power_fired == datetime(2026, 7, 7, 12, 0, tzinfo=TZ8)
