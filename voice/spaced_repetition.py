"""Leitner-box spaced repetition store — simpler than full SM-2, good
enough for lecture Q&A cards. Five boxes with fixed intervals in days;
a correct answer advances one box, an incorrect answer resets to box 1."""
from __future__ import annotations

import json
import uuid
from datetime import date, timedelta
from pathlib import Path

_BOX_INTERVAL_DAYS = {1: 1, 2: 2, 3: 4, 4: 7, 5: 14}
_MAX_BOX = 5


def _store_path() -> Path:
    from voice import config as cfg
    return cfg.get_data_dir() / "spaced_repetition.json"


def _load() -> dict[str, dict]:
    p = _store_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save(data: dict[str, dict]) -> None:
    p = _store_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def add_cards(course: str, cards: list[dict], today: date | None = None) -> int:
    """Add cards (shape: {"q","a","level"}) to the store, all starting in
    box 1, due today. Returns the count added."""
    today = today or date.today()
    data = _load()
    for card in cards:
        card_id = uuid.uuid4().hex[:12]
        data[card_id] = {
            "q": card["q"], "a": card["a"], "level": card.get("level", "recall"),
            "course": course, "box": 1, "due_date": today.isoformat(),
        }
    _save(data)
    return len(cards)


def due_cards(today: date | None = None) -> list[dict]:
    today = today or date.today()
    data = _load()
    out = []
    for card_id, card in data.items():
        if date.fromisoformat(card["due_date"]) <= today:
            out.append({**card, "id": card_id})
    return out


def grade_card(card_id: str, correct: bool, today: date | None = None) -> None:
    today = today or date.today()
    data = _load()
    card = data.get(card_id)
    if card is None:
        return
    if correct:
        card["box"] = min(card["box"] + 1, _MAX_BOX)
    else:
        card["box"] = 1
    interval = _BOX_INTERVAL_DAYS[card["box"]]
    card["due_date"] = (today + timedelta(days=interval)).isoformat()
    _save(data)
