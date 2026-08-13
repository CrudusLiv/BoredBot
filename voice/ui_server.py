"""Vesper visual UI — FastAPI server with WebSocket event broadcast.

Serves the concept graph and streams brain state to the browser.
Runs in a daemon thread; all events are fire-and-forget.

Auth: a random session TOKEN is generated per process start (never persisted).
The initial page load carries it as `?t=`; the orb JS then attaches it as the
`X-Vesper-Token` header on every fetch() and as `?t=` on the /ws handshake.
State-changing POST handlers depend on `_require_token` (401 if missing/
wrong); the WS handshake checks it directly (closes 4401 if invalid).
GET-only endpoints are intentionally left open.

Endpoints:
  GET  /                → orb.html
  POST /input           → typed text → brain.turn() thread; response via WS
  GET  /cmd/finance     → month_summary() JSON
  POST /cmd/finance     → tracker.log(entry) JSON
  GET  /cmd/capabilities → {vault, scripts} availability flags for the UI
  GET  /cmd/llm/status  → active LLM backend/model/availability JSON
  GET  /cmd/llm/detect  → force LLM backend re-detection JSON
  GET  /cmd/calendar    → upcoming events JSON
  GET  /cmd/reminders   → upcoming reminders JSON
  GET  /cmd/tasks       → DEADLINES.md checklist JSON
  GET  /cmd/weather     → wttr.in current conditions JSON
  GET  /cmd/settings    → full config JSON
  GET  /cmd/icon        → extracted app-icon PNG for a PC-control/activity-awareness target
  POST /cmd/settings    → patch one config key JSON
  GET  /cmd/notices     → recent proactive notices JSON
  GET  /cmd/jobs/list   → job-alert postings store JSON
  POST /cmd/jobs/update → set one posting's status JSON
  POST /cmd/jobs/draft  → draft application email into drafts/active/ JSON
  GET  /cmd/drafts      → list entries (typed, drillable) under drafts/active/<dir> JSON
  GET  /cmd/drafts/content → read_note("drafts/active/" + name) JSON
  GET  /cmd/scratch     → list files under scratch/<dir> JSON
  GET  /cmd/scratch/content → read_note("scratch/" + path) JSON
  POST /internal/confirm    → cross-process confirm.request() JSON (for MCP-server subprocess)
  POST /internal/tool-event → cross-process post_event() relay JSON (for MCP-server subprocess)
  WS   /ws              → live brain events
"""
from __future__ import annotations

import asyncio
import os
import secrets
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from voice import ui_window

# Session token: generated once per process start, never persisted to disk.
# Carried by the browser as a `?t=` query param on the initial page load, then
# attached to every fetch() (X-Vesper-Token header) and the /ws handshake
# (`?t=` query param). Gates all state-changing endpoints so that no local
# process or webpage can POST here without having first loaded the orb page.
TOKEN = secrets.token_urlsafe(32)
os.environ["VESPER_UI_TOKEN"] = TOKEN


async def _require_token(x_vesper_token: str | None = Header(None, alias="X-Vesper-Token")) -> None:
    if x_vesper_token != TOKEN:
        raise HTTPException(401, "missing or invalid session token")


def _static_dir() -> Path:
    import sys
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "voice" / "static"  # type: ignore[attr-defined]
    return Path(__file__).parent / "static"


_STATIC = _static_dir()
_clients: list[WebSocket] = []
_queue: asyncio.Queue | None = None
_loop: asyncio.AbstractEventLoop | None = None
_brain = None


def set_brain(brain) -> None:
    """Register the Brain instance so POST /input can call brain.turn()."""
    global _brain
    _brain = brain


def has_clients() -> bool:
    """True when at least one orb UI client is connected to the WebSocket.
    safety.py uses this to decide whether in-orb confirmation can be heard."""
    return len(_clients) > 0


@asynccontextmanager
async def _lifespan(app: FastAPI):
    global _queue, _loop
    _queue = asyncio.Queue()
    _loop = asyncio.get_event_loop()
    asyncio.create_task(_drain())
    yield


app = FastAPI(lifespan=_lifespan)
app.mount("/static", StaticFiles(directory=str(_STATIC)), name="static")


@app.get("/")
async def index() -> HTMLResponse:
    from pathlib import Path as _Path
    from voice import config as cfg
    conf = cfg.load()
    mode = conf.get("ui_render_mode", "orb")
    if mode not in ("orb", "avatar"):
        mode = "orb"
    vrm_name = _Path(conf.get("ui_avatar_vrm_path", "").strip() or "placeholder.vrm").name
    html = (_STATIC / "orb.html").read_text(encoding="utf-8")
    html = html.replace("__VESPER_RENDER_MODE__", mode)
    html = html.replace("__VESPER_AVATAR_VRM_URL__", f"/static/avatar/models/{vrm_name}")
    # Embed the session token server-side so the page works whether it was
    # opened via the tray's app-window launch (?t=... in the URL) or by
    # navigating to this URL directly, e.g. http://localhost:7070 as the
    # README documents — the latter had no token anywhere, so every
    # state-changing request (including the chat box's /input POST) 401'd
    # silently.
    html = html.replace("__VESPER_TOKEN__", TOKEN)
    # no-store: orb.html is re-read from disk on every request (it's the
    # UI's whole codebase, effectively), so a client caching it defeats that
    # -- WebView2's on-disk HTTP cache in particular survives across process
    # restarts (it's tied to the persistent user-data profile, not the
    # process), so "restart Vesper" alone doesn't guarantee a fresh page.
    return HTMLResponse(html, headers={"Cache-Control": "no-store"})


class _TextInput(BaseModel):
    text: str


_ROOT = Path(__file__).resolve().parents[1]


@app.post("/input", status_code=202, dependencies=[Depends(_require_token)])
async def text_input(body: _TextInput) -> Response:
    if _brain is None:
        raise HTTPException(503, "brain not initialised")
    text = body.text.strip()
    if not text:
        raise HTTPException(400, "empty text")

    def _run() -> None:
        try:
            for _ in _brain.turn(text, source="text"):
                pass
        except Exception:
            post_event({"type": "state", "value": "error"})

    threading.Thread(target=_run, daemon=True, name="vesper-input").start()
    return Response(status_code=202)


# ── Capabilities ─────────────────────────────────────────────────────────────

@app.get("/cmd/capabilities")
async def capabilities() -> JSONResponse:
    """Lets the UI hide/gray panels that need infra this install doesn't have,
    instead of failing on click. vault = Obsidian vault (notes/deadlines/graph);
    scripts = .claude/scripts agent layer (finance)."""
    from voice import config as cfg
    return JSONResponse({
        "vault": cfg.get_vault_dir() is not None,
        "scripts": (_ROOT / ".claude" / "scripts").exists(),
    })


# ── Finance panel ────────────────────────────────────────────────────────────

class _FinanceEntry(BaseModel):
    entry: str


@app.get("/cmd/finance")
async def finance_summary() -> JSONResponse:
    def _run():
        import sys
        sys.path.insert(0, str(_ROOT / ".claude" / "scripts"))
        from finance.tracker import month_summary  # type: ignore
        return month_summary()

    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        try:
            summary = ex.submit(_run).result(timeout=10)
            # Additive field only — `summary` keeps its exact prior text/shape
            # so any other consumer of month_summary() (there are none today;
            # verified via repo-wide grep) is unaffected. `empty` lets the
            # frontend render Vesper's own no-data copy instead of the raw
            # backend string, without parsing that string's wording.
            empty = summary.startswith("No expenses logged for ")
            return JSONResponse({"summary": summary, "empty": empty})
        except Exception as exc:
            return JSONResponse({"error": str(exc)}, status_code=500)


@app.post("/cmd/finance", dependencies=[Depends(_require_token)])
async def finance_log(body: _FinanceEntry) -> JSONResponse:
    import sys
    sys.path.insert(0, str(_ROOT / ".claude" / "scripts"))
    try:
        from finance.tracker import parse, log  # type: ignore
    except ImportError as exc:
        return JSONResponse({"error": f"tracker unavailable: {exc}"}, status_code=500)

    parsed = parse(body.entry)
    if not parsed:
        return JSONResponse({"error": "couldn't parse — use: amount category [note]"}, status_code=400)

    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        try:
            result = ex.submit(log, parsed["amount"], parsed["category"], parsed["note"]).result(timeout=10)
            msg = (
                f"Logged RM{parsed['amount']:.2f} · {parsed['category']}"
                + (f" · {parsed['note']}" if parsed["note"] else "")
                + f"\nMonth total: RM{result['month_total']:.2f}"
            )
            return JSONResponse({"message": msg})
        except Exception as exc:
            return JSONResponse({"error": str(exc)}, status_code=500)


# ── LLM status ───────────────────────────────────────────────────────────────

@app.get("/cmd/llm/status")
async def llm_status() -> JSONResponse:
    import asyncio
    from voice import llm
    loop = asyncio.get_event_loop()
    status = await loop.run_in_executor(None, llm.get_status)
    return JSONResponse(status)


@app.get("/cmd/llm/detect")
async def llm_detect() -> JSONResponse:
    import asyncio
    from voice import llm
    loop = asyncio.get_event_loop()
    llm.reset_backend()
    backend = await loop.run_in_executor(None, llm.detect_backend)
    llm.reset_backend()  # force re-cache with new detection on next call
    return JSONResponse({"detected": backend})


# ── Job alerts (Jobs panel) ──────────────────────────────────────────────────────

@app.get("/cmd/jobs/list")
async def jobs_list() -> JSONResponse:
    from voice import config as cfg
    from voice import jobs
    return JSONResponse({"jobs": jobs.load_jobs(cfg.get_data_dir())})


class _JobUpdate(BaseModel):
    id: str
    status: str


@app.post("/cmd/jobs/update", dependencies=[Depends(_require_token)])
async def jobs_update(body: _JobUpdate) -> JSONResponse:
    from voice import config as cfg
    from voice import jobs
    if body.status not in jobs.STATUSES:
        return JSONResponse({"error": f"invalid status '{body.status}'"}, status_code=400)
    if not jobs.update_status(cfg.get_data_dir(), body.id, body.status):
        return JSONResponse({"error": "unknown job id"}, status_code=404)
    return JSONResponse({"ok": True})


class _JobDraft(BaseModel):
    id: str


@app.post("/cmd/jobs/draft", dependencies=[Depends(_require_token)])
async def jobs_draft(body: _JobDraft) -> JSONResponse:
    import asyncio as _asyncio
    from voice import jobs
    # draft_application blocks on the LLM call (up to ~90s) — keep it off
    # the event loop so the orb UI stays responsive while drafting.
    result = await _asyncio.to_thread(jobs.draft_application, body.id)
    if not result.get("ok"):
        return JSONResponse(result, status_code=400)
    return JSONResponse(result)


# ── Calendar ─────────────────────────────────────────────────────────────────

@app.get("/cmd/calendar")
async def calendar_events() -> JSONResponse:
    def _run():
        try:
            import sys
            sys.path.insert(0, str(_ROOT / ".claude" / "scripts"))
            from integrations.gcal_int import upcoming  # type: ignore
            return {"events": upcoming(days=7)}
        except Exception as exc:
            return {"error": str(exc), "events": []}

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, _run)
    return JSONResponse(result)


@app.get("/cmd/reminders")
async def reminders_list() -> JSONResponse:
    def _run():
        try:
            import sys
            sys.path.insert(0, str(_ROOT / ".claude" / "scripts"))
            from integrations import gtasks_write  # type: ignore
            return {"reminders": gtasks_write.list_reminders(days=7)}
        except Exception as exc:
            return {"error": str(exc), "reminders": []}

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, _run)
    return JSONResponse(result)


# ── Tasks / Deadlines ─────────────────────────────────────────────────────────

@app.get("/cmd/tasks")
async def tasks_list() -> JSONResponse:
    import re
    from voice import config as cfg
    vault = cfg.get_vault_dir()
    if vault is None:
        return JSONResponse({"tasks": [], "source": None, "vault_configured": False})
    p = vault / "DEADLINES.md"
    if not p.exists():
        return JSONResponse({"tasks": [], "source": None, "vault_configured": True})
    tasks = []
    for line in p.read_text(encoding="utf-8").splitlines():
        m = re.match(r"[-*]\s+\[( |x|X)\]\s+(.*)", line)
        if m:
            tasks.append({"done": m.group(1).lower() == "x", "text": m.group(2).strip()})
    return JSONResponse({"tasks": tasks, "source": str(p), "vault_configured": True})


# ── Workspace: drafts/active/ + scratch/ ────────────────────────────────────
# Read-only. Writes go through the write_draft/write_scratch tools (voice/
# tools/workspace.py), which are confirmation-free by design (see Task 7).

def _list_vault_dir_typed(rel_dir: str) -> list[dict]:
    """Non-recursive entries under a vault subfolder, each tagged with is_dir
    so the UI can tell folders from files (both drafts/active/ and scratch/
    can nest — e.g. write_draft("sub/x.md", ...) or scratch/notes/x.md — so
    the listing needs to support drilling down rather than trying to read a
    directory's "content"). Missing folder (or anything that isn't a
    directory) is treated as empty, not an error."""
    import sys
    sys.path.insert(0, str(_ROOT / ".claude" / "scripts"))
    from vault import actions, paths  # type: ignore
    try:
        names = actions.list_dir(rel_dir)["entries"]
    except (FileNotFoundError, NotADirectoryError):
        return []
    root = paths.vault() / rel_dir
    return [{"name": n, "is_dir": (root / n).is_dir()} for n in names]


@app.get("/cmd/drafts")
async def drafts_list(dir: str = "") -> JSONResponse:
    rel = f"drafts/active/{dir}" if dir else "drafts/active"
    loop = asyncio.get_event_loop()
    try:
        entries = await loop.run_in_executor(None, _list_vault_dir_typed, rel)
        return JSONResponse({"entries": entries, "dir": dir})
    except Exception as exc:
        return JSONResponse({"error": str(exc), "entries": [], "dir": dir}, status_code=500)


@app.get("/cmd/drafts/content")
async def drafts_content(name: str) -> JSONResponse:
    from voice.tools.vault import read_note
    loop = asyncio.get_event_loop()
    try:
        content = await loop.run_in_executor(None, read_note, f"drafts/active/{name}")
        return JSONResponse({"content": content})
    except Exception as exc:
        return JSONResponse({"error": str(exc), "content": ""}, status_code=500)


@app.get("/cmd/scratch")
async def scratch_list(dir: str = "") -> JSONResponse:
    rel = f"scratch/{dir}" if dir else "scratch"
    loop = asyncio.get_event_loop()
    try:
        entries = await loop.run_in_executor(None, _list_vault_dir_typed, rel)
        return JSONResponse({"entries": entries, "dir": dir})
    except Exception as exc:
        return JSONResponse({"error": str(exc), "entries": [], "dir": dir}, status_code=500)


@app.get("/cmd/scratch/content")
async def scratch_content(path: str) -> JSONResponse:
    from voice.tools.vault import read_note
    loop = asyncio.get_event_loop()
    try:
        content = await loop.run_in_executor(None, read_note, f"scratch/{path}")
        return JSONResponse({"content": content})
    except Exception as exc:
        return JSONResponse({"error": str(exc), "content": ""}, status_code=500)


# ── Weather ───────────────────────────────────────────────────────────────────

@app.get("/cmd/weather")
async def weather() -> JSONResponse:
    import json as _json
    import urllib.parse
    import urllib.request
    from voice import config as cfg
    conf = cfg.load()
    city = conf.get("city", "").strip()
    if not city:
        return JSONResponse({"error": 'no city configured — set "city" in settings'}, status_code=400)
    url = f"https://wttr.in/{urllib.parse.quote(city)}?format=j1"
    try:
        with urllib.request.urlopen(url, timeout=8) as resp:
            data = _json.loads(resp.read())
        cur = data["current_condition"][0]
        return JSONResponse({
            "city": city,
            "temp_c": cur["temp_C"],
            "feels_like_c": cur["FeelsLikeC"],
            "desc": cur["weatherDesc"][0]["value"],
            "humidity": cur["humidity"],
            "wind_kmph": cur["windspeedKmph"],
        })
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


# ── Settings ──────────────────────────────────────────────────────────────────

_SETTINGS_ALLOWED = {
    "user_name", "timezone_offset_hours", "city", "vault_path",
    "tts_engine", "tts_voice", "tts_chatterbox_device", "tts_chatterbox_voice_path",
    "elevenlabs_voice_id", "elevenlabs_batch_chars",
    "stt_beam_size", "stt_vad_filter", "stt_language",
    "llm_backend", "llm_ollama_model", "llm_lmstudio_model",
    "llm_anthropic_model", "heartbeat_interval_minutes",
    "ui_port", "quiet_hours_start", "quiet_hours_end", "proactive_tts",
    "confirm_timeout_seconds", "stream_replies", "catchup_briefing",
    "clap_enabled", "clap_threshold",
    "activity_awareness_enabled", "silence_when_running",
    "downloads_triage_enabled",
    "job_alerts_enabled", "job_alert_senders", "job_alert_lookback_days",
    "pc_control_apps",
    "ptt_key", "screen_read_capture_hotkey", "screen_read_ask_hotkey",
    "screen_read_copy_hotkey", "screen_read_dismiss_hotkey",
}


@app.get("/cmd/settings")
async def settings_get() -> JSONResponse:
    from voice import config as cfg
    return JSONResponse(cfg.load())


@app.get("/cmd/pc-control/apps")
async def pc_control_discover_apps() -> JSONResponse:
    """Scan Start Menu shortcuts for the Config tab's app-name autocomplete
    (voice/tools/pc_control.py::discover_apps). Read-only, so no token
    required -- same tier as GET /cmd/settings."""
    from voice.tools import pc_control
    try:
        return JSONResponse({"apps": pc_control.discover_apps()})
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.get("/cmd/icon")
async def get_icon(target: str) -> Response:
    """Extracted app icon for a PC-control target or activity-awareness exe
    name (voice/tools/icons.py::get_icon_png). Read-only, no token required
    -- same tier as GET /cmd/pc-control/apps. 404 (not a broken image) on
    anything unresolvable, so the frontend's <img onerror> can fall back to
    text-only cleanly."""
    from voice.tools import icons
    loop = asyncio.get_event_loop()
    png = await loop.run_in_executor(None, icons.get_icon_png, target)
    if png is None:
        return JSONResponse({"error": "icon not found"}, status_code=404)
    return Response(
        content=png,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )


class _SettingsPatch(BaseModel):
    key: str
    value: Any


@app.post("/cmd/settings", dependencies=[Depends(_require_token)])
async def settings_patch(body: _SettingsPatch) -> JSONResponse:
    from voice import config as cfg
    if body.key not in _SETTINGS_ALLOWED:
        return JSONResponse({"error": f"key '{body.key}' not patchable"}, status_code=400)
    cfg.save({body.key: body.value})
    return JSONResponse({"ok": True, "key": body.key, "value": body.value})


# ── Notices feed ─────────────────────────────────────────────────────────────

@app.get("/cmd/notices")
async def get_notices() -> JSONResponse:
    import json
    from voice import config as cfg
    p = cfg.get_data_dir() / "voice_notices.jsonl"
    entries: list[dict] = []
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            try:
                entries.append(json.loads(line))
            except Exception:
                pass
    return JSONResponse({"notices": list(reversed(entries[-50:]))})


class _NoticeDismiss(BaseModel):
    id: str | None = None
    all: bool = False
    delete: bool = False  # remove the row entirely instead of marking read


@app.post("/cmd/notices/dismiss", dependencies=[Depends(_require_token)])
async def notices_dismiss(body: _NoticeDismiss) -> JSONResponse:
    import json as _json
    from voice import config as cfg
    if not body.all and not body.id:
        raise HTTPException(400, "id or all required")
    p = cfg.get_data_dir() / "voice_notices.jsonl"
    if not p.exists():
        return JSONResponse({"ok": True, "dismissed": 0})
    entries: list[dict] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                entries.append(_json.loads(line))
            except Exception:
                pass

    def _match(e: dict) -> bool:
        # legacy rows have no id — allow matching by exact ts
        return body.all or e.get("id") == body.id or e.get("ts") == body.id

    dismissed = 0
    if body.delete:
        kept = [e for e in entries if not _match(e)]
        dismissed = len(entries) - len(kept)
        entries = kept
    else:
        for e in entries:
            if _match(e):
                if not e.get("read"):
                    dismissed += 1
                e["read"] = True
    p.write_text(
        "\n".join(_json.dumps(e, ensure_ascii=False) for e in entries)
        + ("\n" if entries else ""),
        encoding="utf-8",
    )
    post_event({"type": "notice_read", **({"all": True} if body.all else {"id": body.id})})
    return JSONResponse({"ok": True, "dismissed": dismissed})


# ── Safety rails ─────────────────────────────────────────────────────────────

class _ConfirmVote(BaseModel):
    id: str
    approve: bool


@app.post("/cmd/confirm", dependencies=[Depends(_require_token)])
async def confirm_vote(body: _ConfirmVote) -> JSONResponse:
    from voice import confirm as _confirm
    if not _confirm.resolve(body.id, body.approve):
        raise HTTPException(404, "confirmation expired or unknown")
    return JSONResponse({"ok": True})


class _InternalConfirm(BaseModel):
    tool: str
    args: dict
    timeout_s: float = 30.0


@app.post("/internal/confirm", dependencies=[Depends(_require_token)])
def internal_confirm(body: _InternalConfirm) -> dict:
    from voice import confirm as _confirm
    approved, reason = _confirm.request(body.tool, body.args, body.timeout_s)
    return {"approved": approved, "reason": reason}


class _InternalEvent(BaseModel):
    event: dict


@app.post("/internal/tool-event", dependencies=[Depends(_require_token)])
def internal_tool_event(body: _InternalEvent) -> dict:
    post_event(body.event)
    return {"ok": True}


class _KillswitchSet(BaseModel):
    paused: bool


@app.get("/cmd/killswitch")
async def killswitch_get() -> JSONResponse:
    from voice import killswitch as _ks
    return JSONResponse({"paused": _ks.is_paused()})


@app.post("/cmd/killswitch", dependencies=[Depends(_require_token)])
async def killswitch_set(body: _KillswitchSet) -> JSONResponse:
    from voice import killswitch as _ks
    return JSONResponse({"paused": _ks.set_paused(body.paused)})


@app.get("/cmd/usage")
async def usage_get() -> JSONResponse:
    from voice import usage as _usage
    return JSONResponse(_usage.summary())


@app.get("/cmd/history")
async def history_get(n: int = 50) -> JSONResponse:
    """Replay recent conversation turns so the orb chat survives a reload."""
    messages: list[dict] = []
    if _brain is not None:
        for turn in list(_brain.history)[-(n * 2):]:
            content = str(turn.get("content", ""))
            if turn.get("role") == "user" and content.startswith("[Tool result for"):
                continue
            if "<tool>" in content:
                continue
            messages.append({"role": turn.get("role"), "content": content})
    return JSONResponse({"messages": messages[-n:]})


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    await ws.accept()
    if ws.query_params.get("t") != TOKEN:
        await ws.close(code=4401)
        return
    _clients.append(ws)
    try:
        while True:
            await ws.receive_text()
    except (WebSocketDisconnect, Exception):
        pass
    finally:
        if ws in _clients:
            _clients.remove(ws)


async def _drain() -> None:
    while True:
        event = await _queue.get()
        for client in list(_clients):
            try:
                await client.send_json(event)
            except Exception:
                if client in _clients:
                    _clients.remove(client)


def post_event(event: dict[str, Any]) -> None:
    """Thread-safe: enqueue an event for broadcast to all WS clients.
    `state` events additionally derive and enqueue an `emotion` event for
    the avatar's face -- see voice/avatar_emotion.py. `state` and
    `killswitch` events also update the tray icon's color/tooltip (see
    voice/tray.py::set_state/set_paused) so the taskbar tray answers
    "is she running/paused" without opening the orb window -- done outside
    the `_loop and _queue` gate below since the tray has no websocket."""
    event_type = event.get("type")
    if event_type == "state":
        from voice import tray
        tray.set_state(event.get("value", ""))
    elif event_type == "killswitch":
        from voice import tray
        tray.set_paused(bool(event.get("paused")))
    if _loop and _queue:
        _loop.call_soon_threadsafe(_queue.put_nowait, event)
        if event_type == "state":
            from voice.avatar_emotion import classify
            derived = classify(event.get("value", ""))
            if derived:
                _loop.call_soon_threadsafe(_queue.put_nowait, derived)


def _open_app_window(port: int) -> None:
    """Open the orb in Edge/Chrome app mode (no browser chrome)."""
    import subprocess, webbrowser
    url = f"http://127.0.0.1:{port}?t={TOKEN}"
    for browser in ["msedge", "chrome", "chromium"]:
        try:
            subprocess.Popen(
                f'start {browser} --app={url} --window-size=900,700',
                shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            return
        except Exception:
            continue
    webbrowser.open(url)


_ui_port: int = 7070  # set by start(); lets open_window() reuse the real port


def _show_window() -> None:
    """Prefer the native pywebview window; fall back to the Edge/Chrome
    subprocess launch if it was never available (see voice/ui_window.py)."""
    if ui_window.is_available():
        ui_window.show()
    else:
        _open_app_window(_ui_port)


def open_window() -> None:
    """Open the orb as its own app window (tray 'Open Vesper')."""
    _show_window()


def ensure_window_open() -> None:
    """Reopen the orb app window only if no UI client is connected.
    Called on wake-word trigger so saying the wake word brings the orb back
    after the window was closed, without spawning duplicates while it's up."""
    if not has_clients():
        _show_window()


def start(port: int = 7070, host: str = "127.0.0.1") -> None:
    """Start uvicorn in a daemon thread. Does not open a window -- the
    caller (voice/main.py::run()) is responsible for that, since
    ui_window.start() must run on the process's real main thread, which
    this function isn't guaranteed to be called from.

    `host` defaults to loopback-only. Set config's `ui_host` to "0.0.0.0"
    to reach the orb from another device (e.g. a phone over Tailscale) --
    every state-changing endpoint still requires the per-process TOKEN, so
    binding wider doesn't remove auth, just loopback-only network scope."""
    global _ui_port
    _ui_port = port

    def _run() -> None:
        import uvicorn
        uvicorn.run(app, host=host, port=port, log_level="error")

    threading.Thread(target=_run, daemon=True, name="vesper-ui").start()
    threading.Event().wait(0.8)
