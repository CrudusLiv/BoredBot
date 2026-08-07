"""Concept Explainer agent — explains a topic using vault lecture notes."""
from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_DIR = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[3])
sys.path.insert(0, str(PROJECT_DIR / ".claude" / "scripts"))

from agents import state as agent_state
from core import llm
from memory.db import connect as _db_connect
from memory.memory_search import hybrid_search

_SYSTEM = """\
You are explaining a CS concept to CrudusLiv, a CS student who is detail-oriented and \
prefers precise, example-driven explanations over vague summaries.

Structure your response as:
**[Concept]**
One-sentence definition.

**How it works**
2–4 bullet points covering the mechanism. Be concrete — use a small example if it helps.

**Why it matters / where it shows up**
1–2 bullets connecting to CS coursework (algorithms, OS, data structures, etc.)

**From your notes** (only if vault excerpts are provided and relevant)
Quote or paraphrase what the notes say, citing the source file name.

Max 280 words. If the vault has nothing useful, say so briefly and answer from general CS knowledge."""


def run(topic: str) -> str:
    conn = _db_connect()
    try:
        chunks = hybrid_search(conn, topic, top_k=6)
    finally:
        conn.close()
    if chunks:
        context_parts = [f"[{c.get('path', '?')}]\n{c['content']}" for c in chunks]
        context = "\n\n".join(context_parts)
    else:
        context = "(no vault notes found)"
    prompt = f"Concept to explain: **{topic}**\n\nVault excerpts:\n{context}"
    result = llm.call(prompt, system_prompt=_SYSTEM, task="concept_explainer") or "Could not generate explanation."
    agent_state.write_agent("concept_explainer", f"Explained: {topic}", "ok" if result else "error")
    return result


if __name__ == "__main__":
    import sys as _sys
    topic = " ".join(_sys.argv[1:]) or "binary search"
    print(run(topic))
