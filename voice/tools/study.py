"""review_cards / grade_card voice tools — spaced-repetition Q&A during
a conversation. The LLM asks the question, hears the user's answer, and
self-grades by calling grade_card with its own correct/incorrect judgment
(there's no exact-string matching — this is a voice conversation)."""
from __future__ import annotations

import json


def review_cards() -> str:
    from voice import spaced_repetition as sr

    due = sr.due_cards()[:10]
    return json.dumps({"cards": [
        {"id": c["id"], "q": c["q"], "a": c["a"], "course": c["course"]} for c in due
    ]})


def grade_card_tool(card_id: str, correct: bool) -> str:
    from voice import spaced_repetition as sr

    sr.grade_card(card_id, correct=correct)
    return json.dumps({"status": "ok"})
