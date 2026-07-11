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
  GET  /cmd/habits      → habits status JSON
  POST /cmd/habits/check → check_pillar(pillar) JSON
  POST /cmd/study/explain → concept_explainer.run(topic) text
  GET  /cmd/study/quiz    → quiz_generator.run() cards JSON
  GET  /cmd/study/plan    → study_planner.run() text
  POST /cmd/study/research → research_synthesizer.run(topic) text
  GET  /cmd/study/progress → progress_monitor.run() text
  GET  /cmd/capabilities → {vault, scripts} availability flags for the UI
  GET  /cmd/llm/status  → active LLM backend/model/availability JSON
  GET  /cmd/llm/detect  → force LLM backend re-detection JSON
  GET  /cmd/apps/scan   → installed apps (Start Menu + registry) JSON
  POST /cmd/apps/approve → approve an app for voice launch JSON
  POST /cmd/apps/revoke  → revoke an approved app JSON
  GET  /cmd/profiles    → profiles.load() JSON
  POST /cmd/profiles    → profiles.create(...) JSON
  POST /cmd/profiles/{id}/update → profiles.update(...) JSON
  POST /cmd/profiles/{id}/delete → profiles.delete(...) JSON
  GET  /cmd/calendar    → upcoming events JSON
  GET  /cmd/tasks       → DEADLINES.md checklist JSON
  GET  /cmd/weather     → wttr.in current conditions JSON
  GET  /cmd/settings    → full config JSON
  POST /cmd/settings    → patch one config key JSON
  GET  /cmd/notices     → recent proactive notices JSON
  GET  /cmd/drafts      → list entries (typed, drillable) under drafts/active/<dir> JSON
  GET  /cmd/drafts/content → read_note("drafts/active/" + name) JSON
  GET  /cmd/scratch     → list files under scratch/<dir> JSON
  GET  /cmd/scratch/content → read_note("scratch/" + path) JSON
  POST /upload          → save .pdf/.pptx to Dynamous/Memory/inbox/
  WS   /ws              → live brain events
"""
from __future__ import annotations

import asyncio
import secrets
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# Session token: generated once per process start, never persisted to disk.
# Carried by the browser as a `?t=` query param on the initial page load, then
# attached to every fetch() (X-Vesper-Token header) and the /ws handshake
# (`?t=` query param). Gates all state-changing endpoints so that no local
# process or webpage can POST here without having first loaded the orb page.
TOKEN = secrets.token_urlsafe(32)


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
    html = (_STATIC / "orb.html").read_text(encoding="utf-8")
    return HTMLResponse(html)


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
    instead of failing on click. vault = Obsidian vault (notes/deadlines/graph/
    uploads); scripts = .claude/scripts agent layer (finance/habits/study)."""
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


# ── Habits panel ─────────────────────────────────────────────────────────────

@app.get("/cmd/habits")
async def habits_status() -> JSONResponse:
    import sys
    sys.path.insert(0, str(_ROOT / ".claude" / "scripts"))
    try:
        from core.habits import get_status_data  # type: ignore
        data = get_status_data()
        # Pydantic can't serialise the returned dict directly if it has non-JSON types
        return JSONResponse({
            "today": data.get("today"),
            "checked": data.get("checked", {}),
            "done_count": data.get("done_count", 0),
            "total": data.get("total", 0),
            "current_streak": data.get("current_streak", 0),
            "best_streak": data.get("best_streak", 0),
        })
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


class _HabitCheck(BaseModel):
    pillar: str


@app.post("/cmd/habits/check", dependencies=[Depends(_require_token)])
async def habits_check(body: _HabitCheck) -> JSONResponse:
    import sys
    sys.path.insert(0, str(_ROOT / ".claude" / "scripts"))
    try:
        from core.habits import check_pillar  # type: ignore
        changed = check_pillar(body.pillar)
        return JSONResponse({"checked": changed})
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


# ── App launcher ─────────────────────────────────────────────────────────────

@app.get("/cmd/apps/scan")
async def apps_scan() -> JSONResponse:
    def _run():
        from voice.app_scanner import scan_all
        return [
            {"name": e.name, "path": e.path, "source": e.source,
             "approved": e.approved, "voice_alias": e.voice_alias}
            for e in scan_all()
        ]
    loop = asyncio.get_event_loop()
    try:
        apps = await loop.run_in_executor(None, _run)
        return JSONResponse({"apps": apps})
    except Exception as exc:
        return JSONResponse({"error": str(exc), "apps": []}, status_code=500)


class _AppApprove(BaseModel):
    path: str
    alias: str


@app.post("/cmd/apps/approve", dependencies=[Depends(_require_token)])
async def apps_approve(body: _AppApprove) -> JSONResponse:
    from voice import approved_apps
    alias = body.alias.strip()
    if not alias:
        return JSONResponse({"error": "alias required"}, status_code=400)
    approved_apps.approve(body.path, alias)
    return JSONResponse({"ok": True, "alias": alias, "path": body.path})


class _AppRevoke(BaseModel):
    path: str = ""
    alias: str = ""


@app.post("/cmd/apps/revoke", dependencies=[Depends(_require_token)])
async def apps_revoke(body: _AppRevoke) -> JSONResponse:
    from voice import approved_apps
    target = body.alias.strip() or body.path.strip()
    if not target:
        return JSONResponse({"error": "alias or path required"}, status_code=400)
    removed = approved_apps.revoke(target)
    return JSONResponse({"ok": removed})


class _DownloadAction(BaseModel):
    path: str


def _download_folders(conf: dict) -> list[str]:
    from voice import downloads
    return conf.get("downloads_watch_folders") or downloads.default_folders()


@app.post("/cmd/downloads/file", dependencies=[Depends(_require_token)])
async def downloads_file(body: _DownloadAction) -> JSONResponse:
    from voice import config as cfg
    from voice import downloads
    conf = cfg.load()
    folders = _download_folders(conf)
    if not downloads.is_under(body.path, folders):
        return JSONResponse({"error": "path is outside the watch folders"}, status_code=400)
    vault = cfg.get_vault_dir()
    if vault is None:
        return JSONResponse({"error": "no vault configured"}, status_code=400)
    result = downloads.file_candidate(body.path, folders, vault / "inbox")
    if not result.get("ok"):
        return JSONResponse(result, status_code=400)
    downloads.mark_seen(cfg.get_data_dir(), body.path, 0.0)   # ensure never re-suggested
    try:
        from voice import heartbeat
        heartbeat.process_inbox_once()   # don't wait for the next slow tick
    except Exception as _e:
        print(f"[ui_server] inbox processing after file error: {_e}", flush=True)
    return JSONResponse(result)


@app.post("/cmd/downloads/dismiss", dependencies=[Depends(_require_token)])
async def downloads_dismiss(body: _DownloadAction) -> JSONResponse:
    from pathlib import Path
    from voice import config as cfg
    from voice import downloads
    conf = cfg.load()
    if not downloads.is_under(body.path, _download_folders(conf)):
        return JSONResponse({"error": "path is outside the watch folders"}, status_code=400)
    try:
        mtime = Path(body.path).stat().st_mtime
    except OSError:
        mtime = 0.0
    downloads.mark_seen(cfg.get_data_dir(), body.path, mtime)
    return JSONResponse({"ok": True})


# ── App-launch profiles ──────────────────────────────────────────────────────
# UI-only CRUD (no voice-callable create/edit/delete — matches how app
# approval itself has no voice path). GET is open; state-changing POSTs are
# token-gated, per this file's convention. See voice/profiles.py (Task 6a)
# for the storage/activation primitives this just exposes over HTTP.

@app.get("/cmd/profiles")
async def profiles_list() -> JSONResponse:
    from voice import profiles
    return JSONResponse({"profiles": profiles.load()})


class _ProfileCreate(BaseModel):
    id: str
    label: str
    apps: list[str]
    trigger: dict | None = None


@app.post("/cmd/profiles", dependencies=[Depends(_require_token)])
async def profiles_create(body: _ProfileCreate) -> JSONResponse:
    from voice import profiles
    profile_id = body.id.strip()
    if not profile_id:
        return JSONResponse({"error": "id required"}, status_code=400)
    try:
        profiles.create(profile_id, body.label, body.apps, body.trigger)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    return JSONResponse({"ok": True, "id": profile_id})


class _ProfileUpdate(BaseModel):
    label: str | None = None
    apps: list[str] | None = None
    trigger: dict | None = None


@app.post("/cmd/profiles/{profile_id}/update", dependencies=[Depends(_require_token)])
async def profiles_update(profile_id: str, body: _ProfileUpdate) -> JSONResponse:
    from voice import profiles
    # exclude_unset (not exclude_none) so a caller can still explicitly clear
    # `trigger` back to null (switching a profile to manual-only) — only
    # fields actually present in the request body are applied.
    fields = body.model_dump(exclude_unset=True)
    try:
        profiles.update(profile_id, **fields)
    except KeyError as exc:
        return JSONResponse({"error": str(exc)}, status_code=404)
    return JSONResponse({"ok": True})


@app.post("/cmd/profiles/{profile_id}/delete", dependencies=[Depends(_require_token)])
async def profiles_delete(profile_id: str) -> JSONResponse:
    from voice import profiles
    removed = profiles.delete(profile_id)
    return JSONResponse({"ok": removed})


# ── Calendar ─────────────────────────────────────────────────────────────────

@app.get("/cmd/calendar")
async def calendar_events() -> JSONResponse:
    def _run():
        try:
            import sys
            sys.path.insert(0, str(_ROOT / ".claude" / "scripts"))
            from integrations.gcal_int import handle_query  # type: ignore
            result = handle_query(["upcoming", "--days", "7", "--json"])
            if isinstance(result, str):
                import json as _j
                try:
                    return _j.loads(result)
                except Exception:
                    return {"events": [], "raw": result}
            if isinstance(result, list):
                return {"events": result}
            return result if isinstance(result, dict) else {"events": []}
        except Exception as exc:
            return {"error": str(exc), "events": []}

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
    "tts_engine", "tts_voice", "elevenlabs_voice_id", "elevenlabs_batch_chars",
    "stt_beam_size", "stt_vad_filter", "stt_language",
    "wakeword_engine", "wakeword_keyword", "wakeword_model",
    "llm_backend", "llm_ollama_model", "llm_lmstudio_model",
    "llm_anthropic_model", "heartbeat_interval_minutes",
    "ui_port", "quiet_hours_start", "quiet_hours_end", "proactive_tts",
    "confirm_timeout_seconds", "stream_replies", "catchup_briefing",
    "clap_enabled", "clap_threshold",
    "activity_awareness_enabled", "silence_when_running",
    "downloads_triage_enabled",
}


@app.get("/cmd/settings")
async def settings_get() -> JSONResponse:
    from voice import config as cfg
    return JSONResponse(cfg.load())


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


# ── Study panel ──────────────────────────────────────────────────────────────

class _StudyQuery(BaseModel):
    topic: str


def _add_scripts_path() -> None:
    import sys
    p = str(_ROOT / ".claude" / "scripts")
    if p not in sys.path:
        sys.path.insert(0, p)


@app.post("/cmd/study/explain", dependencies=[Depends(_require_token)])
async def study_explain(body: _StudyQuery) -> JSONResponse:
    import concurrent.futures
    topic = body.topic.strip()
    if not topic:
        return JSONResponse({"error": "topic required"}, status_code=400)
    def _run():
        _add_scripts_path()
        from agents.concept_explainer import run  # type: ignore
        return run(topic)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        try:
            return JSONResponse({"result": ex.submit(_run).result(timeout=30)})
        except Exception as exc:
            return JSONResponse({"error": str(exc)}, status_code=500)


@app.get("/cmd/study/quiz")
async def study_quiz() -> JSONResponse:
    import concurrent.futures
    def _run():
        _add_scripts_path()
        from agents.quiz_generator import run  # type: ignore
        return run()
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        try:
            return JSONResponse({"cards": ex.submit(_run).result(timeout=30)})
        except Exception as exc:
            return JSONResponse({"error": str(exc)}, status_code=500)


@app.get("/cmd/study/plan")
async def study_plan() -> JSONResponse:
    import concurrent.futures
    def _run():
        _add_scripts_path()
        from agents.study_planner import run  # type: ignore
        return run()
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        try:
            return JSONResponse({"result": ex.submit(_run).result(timeout=30)})
        except Exception as exc:
            return JSONResponse({"error": str(exc)}, status_code=500)


@app.post("/cmd/study/research", dependencies=[Depends(_require_token)])
async def study_research(body: _StudyQuery) -> JSONResponse:
    import concurrent.futures
    topic = body.topic.strip()
    if not topic:
        return JSONResponse({"error": "topic required"}, status_code=400)
    def _run():
        _add_scripts_path()
        from agents.research_synthesizer import run  # type: ignore
        return run(topic)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        try:
            return JSONResponse({"result": ex.submit(_run).result(timeout=30)})
        except Exception as exc:
            return JSONResponse({"error": str(exc)}, status_code=500)


@app.get("/cmd/study/progress")
async def study_progress() -> JSONResponse:
    import concurrent.futures
    def _run():
        _add_scripts_path()
        from agents.progress_monitor import run  # type: ignore
        return run()
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        try:
            return JSONResponse({"result": ex.submit(_run).result(timeout=30)})
        except Exception as exc:
            return JSONResponse({"error": str(exc)}, status_code=500)


# ── File upload (Phase C) ─────────────────────────────────────────────────────

_ALLOWED_EXTS = {".pdf", ".pptx"}


@app.post("/upload", status_code=202, dependencies=[Depends(_require_token)])
async def upload_file(file: UploadFile = File(...)) -> Response:
    from pathlib import Path, PurePosixPath
    from voice import config as cfg
    vault = cfg.get_vault_dir()
    if vault is None:
        raise HTTPException(400, "no vault configured — set vault_path in settings to enable uploads")
    if not cfg.vault_writes_safe():
        raise HTTPException(
            400,
            "vault_path does not match the agent layer's write target — refusing upload",
        )
    suffix = PurePosixPath(file.filename or "").suffix.lower()
    if suffix not in _ALLOWED_EXTS:
        raise HTTPException(400, f"only {_ALLOWED_EXTS} accepted")
    inbox = vault / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    basename = Path(file.filename or ("upload" + suffix)).name
    dest = inbox / basename
    if not dest.resolve().is_relative_to(inbox.resolve()):
        raise HTTPException(400, "invalid filename")
    content = await file.read()
    dest.write_bytes(content)
    return Response(status_code=202)


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
    """Thread-safe: enqueue an event for broadcast to all WS clients."""
    if _loop and _queue:
        _loop.call_soon_threadsafe(_queue.put_nowait, event)


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


def open_window() -> None:
    """Open the orb as its own app window (tray 'Open Vesper')."""
    _open_app_window(_ui_port)


def ensure_window_open() -> None:
    """Reopen the orb app window only if no UI client is connected.
    Called on wake-word trigger so saying the wake word brings the orb back
    after the window was closed, without spawning duplicates while it's up."""
    if not has_clients():
        _open_app_window(_ui_port)


def start(port: int = 7070) -> None:
    """Start uvicorn in a daemon thread and open the browser."""
    global _ui_port
    _ui_port = port

    def _run() -> None:
        import uvicorn
        uvicorn.run(app, host="127.0.0.1", port=port, log_level="error")

    threading.Thread(target=_run, daemon=True, name="vesper-ui").start()
    threading.Event().wait(0.8)

    _open_app_window(port)
