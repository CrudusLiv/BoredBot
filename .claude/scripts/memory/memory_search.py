#!/usr/bin/env python3
"""Hybrid search over the vault: vector (cosine) + keyword (BM25), weighted merge.

Run:
    py .claude/scripts/memory/memory_search.py "regression coefficient"
    py .claude/scripts/memory/memory_search.py "voice match" --path-prefix drafts/sent
    py .claude/scripts/memory/memory_search.py "deadline" --top-k 5 --json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from db import connect  # noqa: E402
from embeddings import embed_one, vec_to_blob  # noqa: E402

VEC_TOP_N = 50
FTS_TOP_N = 50


def fts_safe(query: str) -> str:
    """Strip FTS5 special chars so user queries can't trigger syntax errors."""
    cleaned = re.sub(r'[^\w\s]', ' ', query).strip()
    return cleaned or '""'


def search_vector(conn, query: str, top_n: int, path_prefix: str) -> list[tuple[int, float]]:
    qvec = embed_one(query)
    rows = conn.execute(
        """
        SELECT c.id AS id, vec_distance_cosine(v.embedding, ?) AS dist
        FROM chunks c
        JOIN chunks_vec v ON c.id = v.rowid
        WHERE (? = '' OR c.path LIKE ? || '%')
        ORDER BY dist ASC
        LIMIT ?
        """,
        (vec_to_blob(qvec), path_prefix, path_prefix, top_n),
    ).fetchall()
    return [(r["id"], r["dist"]) for r in rows]


def search_keyword(conn, query: str, top_n: int, path_prefix: str) -> list[tuple[int, float]]:
    safe = fts_safe(query)
    if safe in ("", '""'):
        return []
    rows = conn.execute(
        """
        SELECT c.id AS id, bm25(chunks_fts) AS score
        FROM chunks_fts
        JOIN chunks c ON c.id = chunks_fts.rowid
        WHERE chunks_fts MATCH ?
          AND (? = '' OR c.path LIKE ? || '%')
        ORDER BY score ASC
        LIMIT ?
        """,
        (safe, path_prefix, path_prefix, top_n),
    ).fetchall()
    return [(r["id"], r["score"]) for r in rows]


def normalise_inverted(scored: list[tuple[int, float]]) -> dict[int, float]:
    """Lower raw scores are better (cosine distance, BM25). Map to 0..1 where 1 = best."""
    if not scored:
        return {}
    vals = [s for _, s in scored]
    lo, hi = min(vals), max(vals)
    if hi == lo:
        return {i: 1.0 for i, _ in scored}
    return {i: 1.0 - (s - lo) / (hi - lo) for i, s in scored}


def hybrid_search(
    conn,
    query: str,
    top_k: int = 10,
    path_prefix: str = "",
    vec_weight: float = 0.7,
) -> list[dict]:
    vec_hits = search_vector(conn, query, VEC_TOP_N, path_prefix)
    fts_hits = search_keyword(conn, query, FTS_TOP_N, path_prefix)
    vec_n = normalise_inverted(vec_hits)
    fts_n = normalise_inverted(fts_hits)

    merged = []
    for cid in set(vec_n) | set(fts_n):
        score = vec_weight * vec_n.get(cid, 0.0) + (1.0 - vec_weight) * fts_n.get(cid, 0.0)
        merged.append((cid, score))
    merged.sort(key=lambda x: x[1], reverse=True)
    top = merged[:top_k]
    if not top:
        return []

    placeholders = ",".join("?" * len(top))
    ids = [cid for cid, _ in top]
    rows = conn.execute(
        f"SELECT id, path, heading, content FROM chunks WHERE id IN ({placeholders})",
        ids,
    ).fetchall()
    by_id = {r["id"]: r for r in rows}
    out = []
    for cid, score in top:
        r = by_id.get(cid)
        if not r:
            continue
        out.append({
            "id": r["id"],
            "path": r["path"],
            "heading": r["heading"] or "",
            "content": r["content"],
            "score": round(score, 4),
        })
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Hybrid memory search over the vault.")
    parser.add_argument("query", help="Natural-language search query")
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--path-prefix", default="", help="Restrict to paths starting with this prefix (e.g. 'drafts/sent')")
    parser.add_argument("--vec-weight", type=float, default=0.7, help="0=keyword only, 1=vector only")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of plain text")
    args = parser.parse_args()

    conn = connect()
    try:
        results = hybrid_search(
            conn, args.query, top_k=args.top_k, path_prefix=args.path_prefix, vec_weight=args.vec_weight
        )
    finally:
        conn.close()

    if args.json:
        print(json.dumps(results, indent=2, ensure_ascii=False))
        return 0

    if not results:
        print("(no results)")
        return 0

    for r in results:
        head = f"  [{r['heading']}]" if r["heading"] else ""
        print(f"--- {r['path']}{head}  score={r['score']}")
        snippet = r["content"][:600]
        if len(r["content"]) > 600:
            snippet += "..."
        print(snippet)
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
