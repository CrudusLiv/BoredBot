"""Discord integration -- read-only bot + SQLite cache + CLI query.

ARCHITECTURE
============
The bot is a long-running process (Phase 9 schedules it via Task Scheduler).
It listens on `on_message` and writes every DM and server message into a
SQLite cache. CLI subcommands query that cache, never the live API -- fast,
offline-safe, rate-limit-proof.

SECURITY
========
This module DOES NOT expose a `send_message()` function. Per USER.md, the
agent is forbidden from sending Discord messages. The only carve-out is
Phase 7's DM chat, which lives in `.claude/chat/`. Do not add `send_*`
functions here.

Run the bot:    py discord_int.py        (or: py query.py discord bot)
Query cache:    py query.py discord recent
Prune old msgs: py query.py discord prune
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _env  # noqa: F401, E402  -- loads .env

PROJECT_DIR = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[3])
CACHE_DB = PROJECT_DIR / ".claude" / "data" / "discord_cache.db"
RETENTION_DAYS = 7

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id                    TEXT PRIMARY KEY,
    channel_id            TEXT NOT NULL,
    channel_name          TEXT,
    guild_id              TEXT,
    guild_name            TEXT,
    is_dm                 INTEGER NOT NULL,
    author_id             TEXT NOT NULL,
    author_name           TEXT,
    is_self               INTEGER NOT NULL,
    is_bot                INTEGER NOT NULL,
    content               TEXT,
    created_at            REAL NOT NULL,
    fetched_at            REAL NOT NULL,
    referenced_message_id TEXT,
    referenced_author_id  TEXT
);
CREATE INDEX IF NOT EXISTS idx_msg_created ON messages(created_at);
CREATE INDEX IF NOT EXISTS idx_msg_dm      ON messages(is_dm);
"""


def _connect(db_path: Path | None = None) -> sqlite3.Connection:
    path = db_path or CACHE_DB
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    # Migrate older caches that pre-date the reply-tracking columns.
    cols = {row[1] for row in conn.execute("PRAGMA table_info(messages)").fetchall()}
    if "referenced_message_id" not in cols:
        conn.execute("ALTER TABLE messages ADD COLUMN referenced_message_id TEXT")
    if "referenced_author_id" not in cols:
        conn.execute("ALTER TABLE messages ADD COLUMN referenced_author_id TEXT")
    conn.commit()
    return conn


def prune(retention_days: int = RETENTION_DAYS, db_path: Path | None = None) -> int:
    """Delete messages older than retention_days. Returns deleted row count."""
    cutoff = time.time() - retention_days * 86400
    conn = _connect(db_path)
    try:
        deleted = conn.execute(
            "DELETE FROM messages WHERE created_at < ?", (cutoff,)
        ).rowcount
        conn.commit()
        if deleted:
            conn.execute("VACUUM")
        return deleted
    finally:
        conn.close()


# ---------- Bot (long-running) ----------

def run_bot() -> int:
    token = os.environ.get("DISCORD_BOT_TOKEN")
    if not token:
        print("DISCORD_BOT_TOKEN not set in .env", file=sys.stderr)
        return 1
    try:
        import discord
    except ImportError:
        print("discord.py not installed: py -m pip install -r .claude/requirements.txt", file=sys.stderr)
        return 1

    intents = discord.Intents.default()
    intents.message_content = True
    intents.dm_messages = True
    intents.guilds = True

    client = discord.Client(intents=intents)
    self_id_holder: dict = {"id": None}

    @client.event
    async def on_ready() -> None:
        self_id_holder["id"] = str(client.user.id) if client.user else None
        print(f"Connected as {client.user} (id={self_id_holder['id']})")

    @client.event
    async def on_message(message) -> None:
        try:
            _store_message(message, self_id_holder["id"])
        except Exception as exc:
            print(f"on_message error: {exc}", file=sys.stderr)
            return
        # Immediately capture self-DMs to the vault without waiting for the heartbeat.
        is_dm = message.guild is None
        is_self = self_id_holder["id"] and str(message.author.id) == self_id_holder["id"]
        if is_dm and is_self:
            try:
                import sys as _sys
                _sys.path.insert(0, str(PROJECT_DIR / ".claude" / "scripts"))
                from core import discord_dm_capture
                created_ts = message.created_at.replace(tzinfo=timezone.utc).timestamp()
                discord_dm_capture.route_and_mark({
                    "id": str(message.id),
                    "content": message.content,
                    "created_at": created_ts,
                })
            except Exception as exc:
                print(f"inline dm_capture error: {exc}", file=sys.stderr)

    deleted = prune()
    if deleted:
        print(f"[prune] removed {deleted} messages older than {RETENTION_DAYS}d", file=sys.stderr)
    client.run(token)
    return 0


def _store_message(message, self_id: str | None) -> None:
    is_dm = 1 if message.guild is None else 0
    is_self = 1 if self_id and str(message.author.id) == self_id else 0
    is_bot = 1 if getattr(message.author, "bot", False) else 0
    channel_name = getattr(message.channel, "name", None) or "DM"
    guild_id = str(message.guild.id) if message.guild else None
    guild_name = message.guild.name if message.guild else None
    created_ts = message.created_at.replace(tzinfo=timezone.utc).timestamp()

    referenced_message_id: str | None = None
    referenced_author_id: str | None = None
    ref = getattr(message, "reference", None)
    if ref is not None and getattr(ref, "message_id", None):
        referenced_message_id = str(ref.message_id)
        resolved = getattr(ref, "resolved", None)
        resolved_author = getattr(resolved, "author", None) if resolved is not None else None
        if resolved_author is not None and getattr(resolved_author, "id", None):
            referenced_author_id = str(resolved_author.id)

    conn = _connect()
    try:
        # If the referenced message is in our cache but discord.py didn't resolve it
        # (common for older messages), fall back to a local author lookup.
        if referenced_message_id and referenced_author_id is None:
            row = conn.execute(
                "SELECT author_id FROM messages WHERE id = ?",
                (referenced_message_id,),
            ).fetchone()
            if row:
                referenced_author_id = row["author_id"]
        conn.execute(
            """INSERT OR REPLACE INTO messages
               (id, channel_id, channel_name, guild_id, guild_name, is_dm,
                author_id, author_name, is_self, is_bot, content,
                created_at, fetched_at,
                referenced_message_id, referenced_author_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                str(message.id), str(message.channel.id), channel_name,
                guild_id, guild_name, is_dm,
                str(message.author.id), str(message.author),
                is_self, is_bot, message.content,
                created_ts, time.time(),
                referenced_message_id, referenced_author_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()


# ---------- Cache queries ----------

def recent(hours: int = 24, limit: int = 50, dms_only: bool = False) -> list[dict]:
    if not CACHE_DB.exists():
        return []
    cutoff = time.time() - hours * 3600
    where = "created_at >= ? AND is_self = 0 AND is_bot = 0"
    params: list = [cutoff]
    if dms_only:
        where += " AND is_dm = 1"
    conn = _connect()
    try:
        rows = conn.execute(
            f"SELECT * FROM messages WHERE {where} ORDER BY created_at DESC LIMIT ?",
            params + [limit],
        ).fetchall()
        return [dict(r) for r in rows]
    except Exception as exc:
        print(f"discord_int.recent: DB query failed: {exc}", file=sys.stderr)
        return []
    finally:
        conn.close()


# ---------- CLI ----------

def handle_query(argv: list[str]) -> int:
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(prog="query.py discord")
    parser.add_argument("subcommand", choices=["recent", "dms", "bot", "prune"])
    parser.add_argument("--hours", type=int, default=24)
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    if args.subcommand == "bot":
        return run_bot()

    if args.subcommand == "prune":
        deleted = prune()
        print(f"Pruned {deleted} messages older than {RETENTION_DAYS} days.")
        return 0

    rows = recent(hours=args.hours, limit=args.limit, dms_only=(args.subcommand == "dms"))

    if args.json:
        print(json.dumps(rows, indent=2, ensure_ascii=False, default=str))
        return 0
    if not rows:
        print(f"(no {'DMs' if args.subcommand == 'dms' else 'messages'} in the last {args.hours}h)")
        return 0
    for r in rows:
        when = datetime.fromtimestamp(r["created_at"]).strftime("%Y-%m-%d %H:%M")
        loc = r["channel_name"] if r["is_dm"] else f"{r['guild_name']}#{r['channel_name']}"
        body = (r["content"] or "")[:200]
        print(f"{when}  {loc}  <{r['author_name']}>")
        print(f"    {body}")
    return 0


if __name__ == "__main__":
    sys.exit(run_bot())
