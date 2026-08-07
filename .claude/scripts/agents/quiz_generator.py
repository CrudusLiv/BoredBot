"""Quiz Generator agent — generates flashcard Q&A from a lecture note."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

PROJECT_DIR = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[3])
sys.path.insert(0, str(PROJECT_DIR / ".claude" / "scripts"))

from agents import state as agent_state
from core import llm

VAULT = PROJECT_DIR / "Dynamous" / "Memory"
LECTURES_DIR = VAULT / "lectures"

_SYSTEM = """\
You are a study assistant generating flashcards for a CS student.
Given lecture notes, produce exactly 5 Q&A pairs that cover a mix of:
  - 2 recall questions (define / state)
  - 2 conceptual questions (explain why / compare)
  - 1 application question (trace through / what happens when)

Return ONLY valid JSON — an array of objects, no markdown, no extra text:
[{"q": "...", "a": "...", "level": "recall|concept|apply"}, ...]

Keep questions specific to the note content. Answers should be 1–3 sentences — \
concise enough to read in 10 seconds but complete enough to actually test understanding."""


def _find_latest_lecture() -> Path | None:
    if not LECTURES_DIR.exists():
        return None
    notes = sorted(LECTURES_DIR.rglob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
    return notes[0] if notes else None


def run(from_path: str | None = None) -> list[dict]:
    if from_path:
        note = Path(from_path)
    else:
        note = _find_latest_lecture()

    if note is None or not note.exists():
        agent_state.write_agent("quiz_generator", "No lecture note found", "error")
        return []

    text = note.read_text(encoding="utf-8", errors="ignore")[:6000]
    prompt = f"Generate flashcards from this lecture note:\n\n{text}"
    raw = llm.call_json(prompt, system_prompt=_SYSTEM, task="quiz_generator")

    cards: list[dict] = raw if isinstance(raw, list) else []
    label = f"{len(cards)} Q&A from {note.name}" if cards else "No cards generated"
    agent_state.write_agent("quiz_generator", label, "ok" if cards else "error")
    # attach source name so callers can pass it to format_discord
    for c in cards:
        c.setdefault("_source", note.stem)
    return cards


_LEVEL_EMOJI = {"recall": "📌", "concept": "🧠", "apply": "⚙️"}


def format_discord(cards: list[dict], source_name: str = "") -> str:
    if not cards:
        return "No flashcards generated."
    header = f"**Quiz** — {source_name}\n\n" if source_name else ""
    lines = []
    for i, card in enumerate(cards, 1):
        emoji = _LEVEL_EMOJI.get(card.get("level", ""), "❓")
        lines.append(f"{emoji} **Q{i}.** {card.get('q', '')}\n||{card.get('a', '')}||")
    return header + "\n\n".join(lines)


if __name__ == "__main__":
    cards = run()
    print(format_discord(cards))
