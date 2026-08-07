"""SQLite + sqlite-vec + FTS5 bootstrap for the memory index.

Three storage layers in one DB:
  - `files`        : per-file hash + mtime, used to skip unchanged files on reindex
  - `chunks`       : the textual chunks themselves (id, path, heading, content)
  - `chunks_fts`   : FTS5 mirror of `chunks.content` (auto-synced via triggers)
  - `chunks_vec`   : vec0 virtual table holding 384-dim float embeddings
                     (rowid is kept aligned with chunks.id; manual insert/delete)
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import sqlite_vec

PROJECT_DIR = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[3])
DB_PATH = PROJECT_DIR / ".claude" / "data" / "memory.db"

EMBED_DIM = 384

SCHEMA_CORE = """
CREATE TABLE IF NOT EXISTS files (
    path  TEXT PRIMARY KEY,
    mtime REAL NOT NULL,
    hash  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS chunks (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    path    TEXT NOT NULL,
    heading TEXT,
    content TEXT NOT NULL,
    mtime   REAL NOT NULL,
    hash    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chunks_path ON chunks(path);
"""

SCHEMA_FTS = """
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    content,
    content='chunks',
    content_rowid='id',
    tokenize='porter unicode61'
);

CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON chunks BEGIN
    INSERT INTO chunks_fts(rowid, content) VALUES (new.id, new.content);
END;
CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON chunks BEGIN
    INSERT INTO chunks_fts(chunks_fts, rowid, content) VALUES('delete', old.id, old.content);
END;
CREATE TRIGGER IF NOT EXISTS chunks_au AFTER UPDATE ON chunks BEGIN
    INSERT INTO chunks_fts(chunks_fts, rowid, content) VALUES('delete', old.id, old.content);
    INSERT INTO chunks_fts(rowid, content) VALUES (new.id, new.content);
END;
"""

SCHEMA_VEC = f"""
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_vec USING vec0(
    embedding float[{EMBED_DIM}]
);
"""


def connect(db_path: Path | None = None) -> sqlite3.Connection:
    """Open the memory DB with sqlite-vec loaded and schema initialised."""
    target = db_path or DB_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(target))
    conn.row_factory = sqlite3.Row
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    conn.executescript(SCHEMA_CORE)
    conn.executescript(SCHEMA_FTS)
    conn.executescript(SCHEMA_VEC)
    return conn
