# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

Vesper is a personal second brain. Two layers live here:

1. **Voice app** — the primary interface (`voice/`). Three.js orb UI, push-to-talk audio, faster-whisper STT, Chatterbox Turbo TTS (local, GPU-accelerated, voice-cloning capable; falls back to edge-tts), multi-turn brain via the Claude Agent SDK (`ClaudeSDKClient`, same Max-plan OAuth session `claude -p` always used — no API key needed). The voice app also owns the single proactive heartbeat (`voice/heartbeat.py`, a daemon thread inside the running process — calendar, email, deadlines, GitHub PRs, job alerts, build watch). Run with `py -m voice`.
2. **Claude Code agent system** — `.claude/scripts/`, `.claude/hooks/`, and `.claude/settings.json` are the running agent layer (memory reflection, vector indexing, integrations).

The Discord bot (`chat/discord_bot.py`) is retired — kept for history, not running. The old Discord-routed heartbeat (`.claude/scripts/heartbeat.py`, its `vesper-heartbeat` scheduled task, and the in-thread chat relay `core/thread_chat.py`) is also retired as of this migration — every capability it had now lives in `voice/heartbeat.py`. `core/dashboard.py` + `integrations/discord_webhook.py` are likewise dormant: the morning digest that was their last live caller went away with the academic removal, so nothing in the running system posts through them today. `voice/mcp_server.py` (the `claude -p` subprocess MCP server) is retired the same way — kept for history, not imported by anything — superseded by `voice/agent_tools.py`.

The personal vault (notes, schedules, finances) lives locally at `Dynamous/Memory/` — gitignored. Each machine keeps its own vault.

## Python environment

All tooling targets Python 3.14 (`py` on Windows). Install deps once:

```powershell
py -m pip install -r .claude/requirements.txt
```

Credentials and secrets go in `.env` at the project root — never committed. The `_env.py` loader reads it on import; existing shell env vars take precedence.

## Running Vesper

```powershell
py -m voice              # push-to-talk (default)
py -m voice --text       # text mode
```

Open `http://localhost:7070` in Edge `--app` mode for the orb UI (requires `ui_enabled: true` in `voice/config.json`).

## Running integrations (CLI)

```powershell
# Check which integrations are wired up
py .claude/scripts/query.py status

# Pull data
py .claude/scripts/query.py github pr-list <owner/repo>
py .claude/scripts/query.py gcal upcoming --days 14
py .claude/scripts/query.py gmail recent --days 7
```

Add `--json` to most subcommands for machine-readable output.

## Memory search

```powershell
py .claude/scripts/memory/memory_search.py "your query"
py .claude/scripts/memory/memory_search.py "deadline" --top-k 5 --path-prefix drafts/sent --json
```

Before searching, the index must be built:

```powershell
py .claude/scripts/memory/memory_index.py
```

The DB lives at `.claude/data/memory.db` (gitignored). Embeddings use `fast-all-MiniLM-L6-v2` via FastEmbed (ONNX, local, cached in `.claude/data/fastembed-cache/`).

## Architecture

### Voice app (`voice/`)

| Path | Purpose |
|------|---------|
| `voice/main.py` | Entry point — PTT loop |
| `voice/brain.py` | Multi-turn brain — persistent `ClaudeSDKClient` session, async-to-sync bridge onto a background event loop |
| `voice/agent_tools.py` | In-process `@tool` adapters the SDK calls directly (search, notes, calendar, email, PC control, memory); retires the old `mcp_server.py` subprocess |
| `voice/ui_server.py` | FastAPI server, WebSocket broadcast, sidebar endpoints |
| `voice/static/orb.html` | Three.js orb UI |
| `voice/heartbeat.py` | Daemon thread — calendar, email, deadlines checks |
| `voice/tray.py` | System tray icon + toast notifications |

### Memory layer (`Dynamous/Memory/`)

The vault is the center of everything. Key files loaded into every session via the `SessionStart` hook:

| File | Purpose |
|------|---------|
| `SOUL.md` | Agent personality, voice, hard limits |
| `HEARTBEAT.md` | What the proactive heartbeat checks each tick |
| `daily/YYYY-MM-DD.md` | Per-session logs (last 3 loaded at startup) |

New information always lands in today's `daily/` log first. Durable items are promoted to `MEMORY.md` during the daily reflection — never written there mid-conversation unless explicitly asked.

### Hooks (`.claude/hooks/`)

Three lifecycle hooks wired in `.claude/settings.json`:

- **SessionStart** — runs `session-start-context.py`, injects `SOUL.md` + recent daily logs as `additionalContext`
- **PreCompact** — flushes active context to today's daily log before auto-compaction
- **SessionEnd** — captures decisions on exit

### Scripts (`.claude/scripts/`)

| Path | Role |
|------|------|
| `query.py` | Unified CLI dispatcher — routes subcommands to integration handlers |
| `integrations/_env.py` | Minimal `.env` loader (no python-dotenv) |
| `integrations/registry.py` | Declares integrations + readiness checks against env vars / credential files |
| `integrations/integration_template.py` | Copy this when adding a new integration |
| `memory/db.py` | SQLite schema: `files`, `chunks`, `chunks_fts` (FTS5), `chunks_vec` (sqlite-vec 384-dim) |
| `memory/chunker.py` | Heading-split → size-cap chunker (~400 tokens, 50-token overlap) |
| `memory/embeddings.py` | FastEmbed wrapper |
| `memory/memory_search.py` | Hybrid search: 70% vector + 30% BM25 |
| `memory/memory_index.py` | Walks vault, chunks changed files, upserts into DB |

### Adding an integration

1. Copy `integrations/integration_template.py` → `integrations/<name>_int.py`
2. Implement `handle_query(argv)`
3. Add an `Integration(...)` entry to `integrations/registry.py`
4. Add the key to `DISPATCH` in `query.py`
5. Add required env vars to `.env`

### Google OAuth (Gmail + GCal)

Place `google_credentials.json` at `.claude/data/google_credentials.json`. The token is cached after the first OAuth flow. Both integrations share the same token.

### Settings Management

User settings (quiet hours, feature toggles, heartbeat interval, activity awareness) live in `voice/config.json`, merged over `DEFAULTS` in `voice/config.py` by `config.load()` (an installed `%APPDATA%\Vesper\config.json` wins over the repo copy). Every proactive capability has an independent `*_enabled` flag each heartbeat task checks at the top. Activity awareness adds `activity_awareness_enabled` (opt-in) + `silence_when_running` (list of exe names). There is no `tray_settings.json`.

## Vault write rules

- **Never delete** files under `Dynamous/Memory/`.
- **`drafts/active/` is writable, confirmation-free.** `write_draft(name, text)` (`voice/tools/workspace.py`) writes/overwrites `drafts/active/<name>` — no confirmation prompt, and writing a draft never sends or finalizes anything; it's staging only. Only `active/` is reachable this way — moving a draft to `sent/`/`expired/` is a manual/other-tool action, not something `write_draft` does.
- **`scratch/` is Vesper's own working space** — non-authored, freely overwritable via `write_scratch(path, text)`, and **not indexed by note-search**.
- Neither `drafts/` nor `scratch/` is ever auto-deleted or auto-moved — cleanup is manual, by the user.

## Skills

Skills live in `.claude/skills/<name>/SKILL.md`:

| Skill | Purpose |
|-------|---------|
| `note-search` | Hybrid semantic + keyword search over the vault |
| `vault-structure` | Vault layout, Obsidian conventions, read/write rules |
