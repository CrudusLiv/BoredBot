"""Token/cost tally for LLM calls.

Every call is appended to get_data_dir()/usage.jsonl:
  {"ts": "<ISO8601>", "backend": "ollama", "model": "llama3.2", "in": 120, "out": 80, "cost": 0.0}

Costs come from a static USD-per-million-token table; local backends
(ollama/lmstudio) and unknown models count tokens at zero cost.
"""
from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path

# (input $/Mtok, output $/Mtok) — unknown models fall back to 0 (counted, not priced)
PRICES: dict[str, tuple[float, float]] = {
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-sonnet-4-5": (3.0, 15.0),
    "claude-opus-4-8": (15.0, 75.0),
    "claude-haiku-4-5": (1.0, 5.0),
    "sonnet": (3.0, 15.0),
    "haiku": (1.0, 5.0),
    "opus": (15.0, 75.0),
}

_MAX_BYTES = 10 * 1024 * 1024
_KEEP_LINES = 5000
_lock = threading.Lock()
_today: dict = {"date": "", "calls": 0, "in": 0, "out": 0, "cost": 0.0}


def _path() -> Path:
    from voice import config as cfg
    return cfg.get_data_dir() / "usage.jsonl"


def _price_for(model: str) -> tuple[float, float]:
    m = (model or "").lower()
    for key, price in PRICES.items():
        if m.startswith(key):
            return price
    return (0.0, 0.0)


def _today_str() -> str:
    from voice import config as cfg
    return datetime.now(cfg.get_timezone()).date().isoformat()


def record(backend: str, model: str, input_tokens: int, output_tokens: int,
           cost_usd: float | None = None) -> None:
    """Append one usage row and broadcast the running daily total to the UI.

    cost_usd: pass through an exact figure when the backend reports one
    (claude_cli's total_cost_usd); otherwise computed from PRICES.
    Local backends record cost 0."""
    input_tokens = int(input_tokens or 0)
    output_tokens = int(output_tokens or 0)
    if cost_usd is None:
        if backend in ("ollama", "lmstudio"):
            cost_usd = 0.0
        else:
            pin, pout = _price_for(model)
            cost_usd = (input_tokens * pin + output_tokens * pout) / 1_000_000

    from voice import config as cfg
    entry = {
        "ts": datetime.now(cfg.get_timezone()).isoformat(),
        "backend": backend,
        "model": model,
        "in": input_tokens,
        "out": output_tokens,
        "cost": round(cost_usd, 6),
    }

    with _lock:
        try:
            p = _path()
            p.parent.mkdir(parents=True, exist_ok=True)
            with p.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
            _maybe_rotate(p)
        except OSError:
            pass

        today = _today_str()
        if _today["date"] != today:
            _today.update({"date": today, "calls": 0, "in": 0, "out": 0, "cost": 0.0})
        _today["calls"] += 1
        _today["in"] += input_tokens
        _today["out"] += output_tokens
        _today["cost"] += cost_usd
        snapshot = dict(_today)

    try:
        from voice import ui_server
        ui_server.post_event({
            "type": "usage",
            "today_cost": round(snapshot["cost"], 6),
            "today_in": snapshot["in"],
            "today_out": snapshot["out"],
            "calls": snapshot["calls"],
        })
    except Exception:
        pass


def _maybe_rotate(p: Path) -> None:
    try:
        if p.stat().st_size < _MAX_BYTES:
            return
        lines = p.read_text(encoding="utf-8").splitlines()
        if len(lines) > _KEEP_LINES:
            p.write_text("\n".join(lines[-_KEEP_LINES:]) + "\n", encoding="utf-8")
    except OSError:
        pass


def summary() -> dict:
    """Aggregate today and the trailing 7 days from usage.jsonl."""
    from datetime import timedelta
    from voice import config as cfg

    now = datetime.now(cfg.get_timezone())
    today = now.date().isoformat()
    week_floor = (now - timedelta(days=7)).isoformat()

    day = {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}
    week = {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}
    try:
        with _path().open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                ts = row.get("ts", "")
                if ts < week_floor:
                    continue
                week["calls"] += 1
                week["input_tokens"] += int(row.get("in", 0))
                week["output_tokens"] += int(row.get("out", 0))
                week["cost_usd"] += float(row.get("cost", 0.0))
                if ts.startswith(today):
                    day["calls"] += 1
                    day["input_tokens"] += int(row.get("in", 0))
                    day["output_tokens"] += int(row.get("out", 0))
                    day["cost_usd"] += float(row.get("cost", 0.0))
    except OSError:
        pass

    day["cost_usd"] = round(day["cost_usd"], 6)
    week["cost_usd"] = round(week["cost_usd"], 6)
    return {"today": day, "week": week}
