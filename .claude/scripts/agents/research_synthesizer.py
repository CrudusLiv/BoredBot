"""Research Synthesiser agent — cross-references a topic across all vault notes."""
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
You are a research synthesis assistant for a CS student.
Given excerpts from their personal vault on a topic, produce a structured synthesis.

**Core idea**
1–2 sentences capturing the essence of what the notes say.

**Key points** (from the vault)
3–5 bullets. Cite the source note name in brackets after each point, e.g. [week3-os].

**Connections**
1–2 bullets linking this topic to other CS concepts (if the notes suggest them).

**Gaps / what's missing**
One sentence on what the notes don't cover that would be worth studying.

Max 300 words. If fewer than 2 useful excerpts exist, say so and give a brief \
general overview from CS knowledge instead."""


def run(topic: str) -> str:
    conn = _db_connect()
    try:
        chunks = hybrid_search(conn, topic, top_k=8)
    finally:
        conn.close()
    if not chunks:
        result = f"No vault notes found on '{topic}'."
        agent_state.write_agent("research_synth", result, "idle")
        return result

    context = "\n\n".join(
        f"[{c.get('path', '?')}]\n{c['content']}" for c in chunks
    )
    prompt = f"Topic: {topic}\n\nVault excerpts:\n{context}"
    result = llm.call(prompt, system_prompt=_SYSTEM, task="research_synth") or "Could not synthesise."
    agent_state.write_agent("research_synth", f"Synthesised {len(chunks)} notes on {topic}")
    return result


if __name__ == "__main__":
    import sys as _sys
    topic = " ".join(_sys.argv[1:]) or "algorithms"
    print(run(topic))
