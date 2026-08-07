#!/usr/bin/env python3
"""Incremental indexer for the vault.

Walks the included subset of `Dynamous/Memory/`, hashes each file, and only
re-embeds files whose hash changed since the last run. Files that disappear
from the vault between runs are removed from the index.

Run directly:  py .claude/scripts/memory/memory_index.py
"""
from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from chunker import chunk_markdown  # noqa: E402
from db import connect  # noqa: E402
from embeddings import embed, vec_to_blob  # noqa: E402

PROJECT_DIR = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[3])
VAULT = PROJECT_DIR / "Dynamous" / "Memory"

# What to index. Anything outside these is ignored.
INCLUDE_FILES = ["SOUL.md", "USER.md", "MEMORY.md", "HEARTBEAT.md", "HABITS.md"]
INCLUDE_DIRS = ["lectures", "projects", "research", "goals", "daily", "drafts/sent"]


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def discover_files() -> list[Path]:
    files: list[Path] = []
    for fname in INCLUDE_FILES:
        p = VAULT / fname
        if p.exists() and p.is_file():
            files.append(p)
    for d in INCLUDE_DIRS:
        dpath = VAULT / d
        if not dpath.exists():
            continue
        for p in dpath.rglob("*.md"):
            if p.name == ".gitkeep":
                continue
            files.append(p)
    return files


def remove_file(conn, rel_path: str) -> None:
    """Drop a file's chunks from the chunks + chunks_vec tables."""
    rows = conn.execute("SELECT id FROM chunks WHERE path = ?", (rel_path,)).fetchall()
    for row in rows:
        conn.execute("DELETE FROM chunks_vec WHERE rowid = ?", (row["id"],))
    conn.execute("DELETE FROM chunks WHERE path = ?", (rel_path,))
    conn.execute("DELETE FROM files WHERE path = ?", (rel_path,))


def index_file(conn, path: Path) -> int:
    rel = str(path.relative_to(VAULT)).replace("\\", "/")
    h = file_hash(path)
    mtime = path.stat().st_mtime

    row = conn.execute("SELECT hash FROM files WHERE path = ?", (rel,)).fetchone()
    if row and row["hash"] == h:
        return 0

    remove_file(conn, rel)

    text = path.read_text(encoding="utf-8")
    chunks = chunk_markdown(text)
    if not chunks:
        conn.execute(
            "INSERT OR REPLACE INTO files(path, mtime, hash) VALUES (?, ?, ?)",
            (rel, mtime, h),
        )
        conn.commit()
        return 0

    vectors = embed([c.content for c in chunks])
    for chunk, vec in zip(chunks, vectors):
        cur = conn.execute(
            "INSERT INTO chunks(path, heading, content, mtime, hash) VALUES (?, ?, ?, ?, ?)",
            (rel, chunk.heading, chunk.content, mtime, h),
        )
        conn.execute(
            "INSERT INTO chunks_vec(rowid, embedding) VALUES (?, ?)",
            (cur.lastrowid, vec_to_blob(vec)),
        )

    conn.execute(
        "INSERT OR REPLACE INTO files(path, mtime, hash) VALUES (?, ?, ?)",
        (rel, mtime, h),
    )
    conn.commit()
    return len(chunks)


def cleanup_deleted(conn, current_relpaths: set[str]) -> int:
    indexed = {row["path"] for row in conn.execute("SELECT path FROM files")}
    gone = indexed - current_relpaths
    for rel in gone:
        remove_file(conn, rel)
    return len(gone)


def main() -> int:
    if not VAULT.exists():
        print(f"Vault not found at {VAULT}", file=sys.stderr)
        return 1
    conn = connect()
    files = discover_files()
    rel_set = {str(p.relative_to(VAULT)).replace("\\", "/") for p in files}

    deleted = cleanup_deleted(conn, rel_set)
    if deleted:
        conn.commit()
        print(f"  removed {deleted} deleted file(s) from index")

    indexed_count = 0
    chunk_count = 0
    for f in files:
        n = index_file(conn, f)
        if n > 0:
            indexed_count += 1
            chunk_count += n
            print(f"  indexed {f.relative_to(VAULT)} ({n} chunks)")

    total_chunks = conn.execute("SELECT COUNT(*) AS c FROM chunks").fetchone()["c"]
    total_files = conn.execute("SELECT COUNT(*) AS c FROM files").fetchone()["c"]
    conn.close()

    if indexed_count == 0 and deleted == 0:
        print(f"No changes. Index has {total_chunks} chunks across {total_files} files.")
    else:
        print(
            f"Done. Indexed {chunk_count} chunks across {indexed_count} changed file(s). "
            f"Index now holds {total_chunks} chunks across {total_files} files."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
