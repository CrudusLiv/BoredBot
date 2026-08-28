"""Load and save voice config. Merges with defaults so new keys added
to DEFAULTS are available even in older config files.

Search order for config.json:
  1. voice/config.json                (repo defaults / dev)
  2. %APPDATA%/Vesper/config.json     (user-specific, wins over dev defaults)

Runtime data (session, logs, notices) always goes to get_data_dir().
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

_DEV_CONFIG = Path(__file__).parent / "config.json"


def _appdata_dir() -> Path:
    appdata = os.environ.get("APPDATA", "")
    if appdata:
        return Path(appdata) / "Vesper"
    return Path.home() / ".vesper"


def _installed_config() -> Path:
    return _appdata_dir() / "config.json"


DEFAULTS: dict[str, Any] = {
    # Identity
    "user_name": "User",
    "timezone_offset_hours": 0,
    "data_dir": "",                 # empty = auto (%APPDATA%\Vesper\ or ~/.vesper/)
    "vault_path": "",               # optional Obsidian vault; empty = notes/deadlines features disabled
    # Models
    "model": "claude-sonnet-4-6",
    # LLM backend routing
    "llm_backend": "auto",          # auto | claude_cli | anthropic | ollama | lmstudio
    "llm_ollama_model": "llama3.2",
    "llm_lmstudio_model": "local-model",
    "llm_anthropic_model": "claude-sonnet-4-6",
    # TTS
    "tts_engine": "chatterbox",     # chatterbox | edge | kokoro | elevenlabs
    "tts_chatterbox_device": "cuda",  # cuda | cpu (falls back to cpu if cuda init fails)
    "tts_chatterbox_voice_path": "",  # optional local .wav reference clip (>5s) for voice cloning
    "tts_voice": "en-GB-SoniaNeural",
    "tts_kokoro_voice": "bf_isabella",
    "tts_preload_kokoro": False,
    "elevenlabs_voice_id": "",
    "elevenlabs_batch_chars": 250,  # buffer sentences to this size before an ElevenLabs synth call (credit conservation)
    # Input
    "ptt_key": "`",
    "max_history_turns": 40,
    # Quiet hours
    "quiet_hours_start": "22:00",
    "quiet_hours_end": "09:00",
    # Heartbeat
    "heartbeat_enabled": True,
    "heartbeat_interval_minutes": 30,
    # Idle-return context trigger
    "context_poll_seconds": 60,
    "idle_return_enabled": True,
    "idle_return_threshold_minutes": 20,
    "idle_return_cooldown_minutes": 15,
    # Activity awareness (process-based silence + reactive triggers)
    "activity_awareness_enabled": False,   # opt-in; dormant until enabled
    "silence_when_running": [],            # lowercase exe names, e.g. ["zoom.exe", "teams.exe"]
    # PC control (voice/tools/pc_control.py) — launch_app is allowlist-only:
    # {"spoken name": "path or command os.startfile() will run"}, e.g.
    # {"spotify": "spotify:", "notepad": "notepad.exe"}. Empty by default —
    # opt-in, the user configures which apps voice can launch.
    "pc_control_apps": {},
    # File search (voice/tools/filesearch.py) — read-only name/content search.
    # filesearch_roots: [] uses a default set (~/Desktop, ~/Documents,
    # ~/Downloads, D:\GitHub, D:\University); a non-empty list replaces it
    # entirely. filesearch_denylist: filename / path-segment globs that are
    # never scanned or returned, even under an allowed root.
    "filesearch_roots": [],
    "filesearch_denylist": [
        ".env", ".ssh", "*.key", "*.pem", "*.pfx", "id_rsa",
        "credentials", "*.sqlite", "AppData",
    ],
    # UI
    "ui_enabled": False,
    "ui_port": 7070,
    "ui_host": "127.0.0.1",         # bind address for the FastAPI/uvicorn server; set "0.0.0.0" to reach it from other devices (e.g. over Tailscale)
    "city": "",                     # for weather widget; empty = disabled
    "ui_render_mode": "orb",        # orb | face
    "ui_face_png_path": "",         # filename under voice/static/face/; empty = vesper.png
    "ui_face_mode": "points",       # points (cloud) | overlay (art + silhouette aura)
    "ui_face_point_count": 40000,   # points sampled from the PNG in `points` mode
    # In-page hotkeys (browser keydown, not the global GetAsyncKeyState poll).
    # Same spec grammar as ptt_key -- see voice/keys.py.
    "ui_dock_hotkey": "right",
    "ui_undock_hotkey": "left",
    "ui_confirm_yes_hotkey": "y",
    "ui_confirm_no_hotkey": "n",
    # Speaking ducking + popup
    "audio_duck_enabled": False,    # opt-in; lowers other apps' Windows audio sessions while she speaks (needs pycaw)
    "audio_duck_percent": 25,       # other sessions' volume is scaled to this % of their current level
    "speaking_popup_enabled": True,  # only relevant when ui_enabled is on -- shows a mini waveform-capsule popup while she speaks and the main orb window is closed
    "speaking_popup_corner": "middle-right",  # top-left | top-right | middle-left | middle-right | bottom-left | bottom-right
    # Safety
    "requires_confirmation": ["create_note", "append_note", "forget_fact", "create_calendar_event"],
    "confirm_timeout_seconds": 30,
    "killswitch_voice_phrases": ["stand down", "pause yourself", "resume duties"],
    # Streaming replies (sentence-by-sentence TTS pipeline)
    "stream_replies": True,
    "stream_min_sentence_chars": 24,
    # Heartbeat catch-up
    "catchup_briefing": True,
    "catchup_max_age_hours": 12,
    # STT
    "stt_model": "base",
    "stt_device": "cpu",
    "stt_compute_type": "int8",
    "stt_beam_size": 1,
    "stt_vad_filter": True,
    "stt_vad_min_silence_ms": 300,
    "stt_language": "en",
    # Proactive TTS
    "proactive_tts": True,
    "briefing_enabled": True,
    "briefing_time": "09:00",
    "wrap_time": "21:00",
    "nudge_enabled": True,
    "nudge_minutes": 15,
    # How often the nudge check itself runs -- must stay comfortably below
    # nudge_minutes, or an event's heads-up window can close between polls
    # and never get caught. If you tighten nudge_minutes a lot, tighten
    # this too.
    "nudge_check_interval_minutes": 5,
    "gcal_sync_enabled": True,
    "gcal_sync_interval_minutes": 5,
    "github_digest_enabled": True,
    "github_digest_interval_minutes": 5,
    "deadline_threshold_enabled": True,
    "git_todo_summary_enabled": True,
    "git_todo_summary_time": "20:00",
    "build_watch_enabled": True,
    "build_watch_time": "07:30",
    "build_watch_repo": "",
    # Daily vault-log rollup (voice/heartbeat.py _check_vault_daily_rollup):
    # once a day, past vault_rollup_time, append voice conversation
    # highlights + the day's heartbeat notices + a finance summary to
    # Dynamous/Memory/daily/YYYY-MM-DD.md -- the only durable record of
    # those three, since none of them otherwise reach the vault.
    "vault_rollup_enabled": True,
    "vault_rollup_time": "23:30",
    # GCal → DEADLINES.md import (reverse of the vault→GCal push)
    "deadline_import_enabled": True,
    "deadline_import_keywords": [
        "due", "deadline", "submission", "submit", "payment", "bill",
        "renewal", "expires", "application", "interview", "appointment",
    ],
    "deadline_import_lookahead_days": 30,
    "deadline_import_lookback_days": 3,
    # Job alerts (email-digest job tracker; Jobs panel in the orb UI)
    "job_alerts_enabled": False,           # opt-in: scan Gmail for job-alert digests
    "job_alert_senders": ["linkedin.com", "indeed.com", "glassdoor.com"],
    "job_alert_lookback_days": 3,
    # Empty = scan the primary Google account (shared with Calendar/Tasks).
    # A label here scans a separate Google account instead, authorized
    # independently (see .claude/scripts/integrations/google_auth.py).
    "job_alert_account": "",
    # Urgent email (event-triggered heartbeat check, replaces the old
    # interval-based raw-count announcement)
    "urgent_email_enabled": True,
    "urgent_email_lookback_days": 1,
    # Reminder nags: repeat a spoken reminder every reminder_nag_interval_minutes
    # for every due-or-overdue Google Tasks reminder until it's marked done
    # (voice: "mark <title> done", or complete_reminder_tool).
    "reminder_nag_enabled": True,
    "reminder_nag_interval_minutes": 120,
    # Clap detector
    "clap_enabled": False,
    "clap_threshold": 0.7,
    "clap_window_s": 0.8,
    # VAD
    "vad_silence_s": 0.6,
    "vad_max_s": 8.0,
    "vad_silence_threshold": 0.01,
    # Screen-read overlay (capture -> vision call -> never-focus overlay)
    "screen_read_enabled": False,          # opt-in; dormant until enabled
    "screen_read_capture_hotkey": "f9",
    "screen_read_ask_hotkey": "f10",
    "screen_read_copy_hotkey": "f11",
    "screen_read_dismiss_hotkey": "f12",
}


def get_data_dir() -> Path:
    """Return the runtime data directory (session, logs, notices), creating it if needed."""
    custom = load().get("data_dir", "")
    p = Path(custom) if custom else _appdata_dir()
    p.mkdir(parents=True, exist_ok=True)
    return p


def get_timezone() -> timezone:
    """Return a timezone built from the configured UTC offset (hours)."""
    offset = load().get("timezone_offset_hours", 0)
    return timezone(timedelta(hours=float(offset)))


def get_user_name() -> str:
    """Return the configured display name."""
    return load().get("user_name", "User")


def get_face_png_name(conf: dict[str, Any] | None = None) -> str:
    """Filename (no directory) of the configured face-render PNG under static/face/."""
    if conf is None:
        conf = load()
    return Path(conf.get("ui_face_png_path", "").strip() or "vesper.png").name


def get_vault_dir() -> Path | None:
    """Return the configured Obsidian vault directory, or None if not configured.

    Falls back to the repo-local Dynamous/Memory dev vault only when running
    unfrozen and that folder actually exists — never in a packaged .exe, since
    the "repo root" there is a meaningless temp extraction path."""
    import sys
    custom = load().get("vault_path", "").strip()
    if custom:
        p = Path(custom)
        return p if p.exists() else None
    if not getattr(sys, "frozen", False):
        dev_vault = get_vault_write_root()
        if dev_vault is not None:
            return dev_vault
    return None


def get_vault_write_root() -> Path | None:
    """Return the vault root that .claude/scripts/vault/actions.py actually
    writes to (mirrors that module's own CLAUDE_PROJECT_DIR-or-repo-root
    resolution), independent of the vault_path setting. Used to detect a
    mismatch before allowing remember()/append_note()/create_note() to write."""
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR")
    root = Path(project_dir) if project_dir else Path(__file__).resolve().parents[1]
    p = root / "Dynamous" / "Memory"
    return p if p.exists() else None


def vault_writes_safe() -> bool:
    """True if get_vault_dir() and the agent-layer's actual write target
    resolve to the same folder — i.e. remember()/append_note() etc. will
    write to the vault you think they will."""
    read_root = get_vault_dir()
    write_root = get_vault_write_root()
    if read_root is None or write_root is None:
        return False
    return read_root.resolve() == write_root.resolve()


def load() -> dict[str, Any]:
    """Return config merged with defaults. Installed config wins over dev config."""
    on_disk: dict[str, Any] = {}
    for path in (_DEV_CONFIG, _installed_config()):   # installed applied last → wins
        if path.exists():
            try:
                on_disk.update(json.loads(path.read_text(encoding="utf-8")))
            except (json.JSONDecodeError, OSError):
                pass
    return {**DEFAULTS, **on_disk}


def save(updates: dict[str, Any]) -> None:
    """Merge `updates` into the user's installed config (creates it if needed)."""
    installed = _installed_config()
    installed.parent.mkdir(parents=True, exist_ok=True)
    current: dict[str, Any] = {}
    if installed.exists():
        try:
            current = json.loads(installed.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    current.update(updates)
    installed.write_text(
        json.dumps(current, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def is_quiet_hours() -> bool:
    """Return True if current local time falls within quiet_hours_start–quiet_hours_end."""
    conf = load()
    start_str = conf.get("quiet_hours_start", "22:00")
    end_str = conf.get("quiet_hours_end", "09:00")
    now = datetime.now(get_timezone())
    now_min = now.hour * 60 + now.minute
    sh, sm = (int(x) for x in start_str.split(":"))
    eh, em = (int(x) for x in end_str.split(":"))
    start_min = sh * 60 + sm
    end_min = eh * 60 + em
    if start_min > end_min:  # window crosses midnight (e.g. 22:00–09:00)
        return now_min >= start_min or now_min < end_min
    return start_min <= now_min < end_min
