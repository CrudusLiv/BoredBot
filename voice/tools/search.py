"""Vault search: hybrid vector + BM25 over the memory index."""
from __future__ import annotations
import sqlite3
from pathlib import Path
import voice  # noqa: F401

_DB = Path(__file__).resolve().parents[2] / ".claude" / "data" / "memory.db"


def search_vault(query: str, top_k: int = 5) -> str:
    if not _DB.exists():
        return "Search index not built. Run: py .claude/scripts/memory/memory_index.py"
    try:
        from memory.memory_search import hybrid_search  # type: ignore
        conn = sqlite3.connect(str(_DB))
        conn.row_factory = sqlite3.Row
        try:
            results = hybrid_search(conn, query, top_k=top_k)
        finally:
            conn.close()
    except Exception as exc:
        return f"Search error: {exc}"
    if not results:
        return f"No results for: {query!r}"
    lines = [f"{len(results)} result(s) for {query!r}:"]
    for i, r in enumerate(results, 1):
        path = r.get("path", "?")
        heading = r.get("heading") or ""
        snippet = (r.get("content") or r.get("text") or "")[:150]
        loc = f" > {heading}" if heading else ""
        lines.append(f"{i}. [{path}]{loc}: {snippet}...")
    return "\n".join(lines)
