"""One-shot readiness probes for the UI's boot checklist.

Each probe returns (status, detail) and is individually wrapped by run_all(),
so a probe that raises becomes its own failed row rather than a 500 on the
endpoint. Nothing here blocks startup -- Vesper degrades rather than halting,
and the checklist reports that instead of changing it.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable, TypedDict

_ROOT = Path(__file__).resolve().parents[1]


class Check(TypedDict):
    id: str
    label: str
    detail: str
    status: str   # ok | fail | skip
    error: str


def _stt() -> tuple[str, str]:
    from voice import config as cfg
    conf = cfg.load()
    try:
        import faster_whisper  # noqa: F401
    except ImportError:
        return "fail", "faster-whisper not installed"
    return "ok", f"faster-whisper/{conf.get('stt_model', 'base')} on {conf.get('stt_device', 'cpu')}"


def _tts() -> tuple[str, str]:
    import importlib
    from voice import config as cfg
    conf = cfg.load()
    engine = conf.get("tts_engine", "chatterbox")
    if engine == "elevenlabs":
        import os
        if not os.environ.get("ELEVENLABS_API_KEY", "").strip():
            return "fail", "ELEVENLABS_API_KEY not set -- falls back to edge-tts"
        return "ok", engine
    module = {"chatterbox": "chatterbox.tts_turbo", "kokoro": "kokoro"}.get(engine, "edge_tts")
    try:
        importlib.import_module(module)
    except ImportError:
        return "fail", f"{engine} not installed -- falls back to edge-tts"
    if engine == "chatterbox":
        return "ok", f"chatterbox/{conf.get('tts_chatterbox_device', 'cuda')}"
    return "ok", engine


def _llm() -> tuple[str, str]:
    from voice import llm
    status = llm.get_status()
    if not status["available"]:
        return "fail", f"{status['backend']} unreachable"
    return "ok", f"{status['backend']}/{status['model']}"


def _vault() -> tuple[str, str]:
    from voice import config as cfg
    path = cfg.get_vault_dir()
    if path is None:
        return "skip", "not configured"
    return "ok", Path(path).name


def _memory() -> tuple[str, str]:
    db = _ROOT / ".claude" / "data" / "memory.db"
    if not db.exists():
        return "fail", "memory.db missing -- run memory_index.py"
    import sqlite3
    conn = sqlite3.connect(db)
    try:
        count = conn.execute("SELECT count(*) FROM chunks").fetchone()[0]
    finally:
        conn.close()
    return "ok", f"{count} chunks"


def _google() -> tuple[str, str]:
    data = _ROOT / ".claude" / "data"
    if not (data / "google_credentials.json").exists():
        return "skip", "no credentials file"
    tokens = sorted(p.stem[len("google_token_"):] if p.stem.startswith("google_token_") else "primary"
                    for p in data.glob("google_token*.json"))
    if not tokens:
        return "fail", "credentials present but no cached token -- reauth needed"
    return "ok", ", ".join(tokens)


def _heartbeat() -> tuple[str, str]:
    from voice import config as cfg
    conf = cfg.load()
    if not conf.get("heartbeat_enabled", True):
        return "skip", "disabled"
    return "ok", f"every {conf.get('heartbeat_interval_minutes', 30)}m"


def _scripts() -> tuple[str, str]:
    if not (_ROOT / ".claude" / "scripts").exists():
        return "skip", "agent layer not present"
    return "ok", ".claude/scripts"


def _face() -> tuple[str, str]:
    from voice import config as cfg
    conf = cfg.load()
    if conf.get("ui_render_mode") != "face":
        return "skip", "orb mode"
    name = cfg.get_face_png_name(conf)
    png = Path(__file__).resolve().parent / "static" / "face" / name
    if not png.exists():
        return "fail", f"{name} missing -- falling back to orb"
    return "ok", f"{name} ({conf.get('ui_face_mode', 'points')})"


PROBES: dict[str, tuple[str, Callable[[], tuple[str, str]]]] = {
    "stt":       ("STT",       _stt),
    "tts":       ("TTS",       _tts),
    "llm":       ("LLM",       _llm),
    "vault":     ("VAULT",     _vault),
    "memory":    ("MEMORY",    _memory),
    "google":    ("GOOGLE",    _google),
    "heartbeat": ("HEARTBEAT", _heartbeat),
    "scripts":   ("SCRIPTS",   _scripts),
    "face":      ("FACE",      _face),
}


def run_all() -> list[Check]:
    """Run every probe. A probe that raises becomes a failed row."""
    rows: list[Check] = []
    for check_id, (label, probe) in PROBES.items():
        try:
            status, detail = probe()
            rows.append(Check(id=check_id, label=label, detail=detail,
                              status=status, error=""))
        except Exception as exc:
            rows.append(Check(id=check_id, label=label, detail="",
                              status="fail", error=str(exc)))
    return rows
