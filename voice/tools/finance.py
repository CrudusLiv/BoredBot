"""Finance logging: wraps .claude/scripts/finance/tracker.py.

Confirmation-free by design, unlike append_note/create_note: the operation
is narrow (one structured row into finance/YYYY-MM.md plus a recompute of
the derived Summary/Timeline sections), additive-only, and requiring a
confirmation on every "log 20 ringgit lunch" would defeat the point of
voice capture.
"""
from __future__ import annotations
import voice  # noqa: F401 — sys.path setup for .claude/scripts
from finance import tracker  # type: ignore


def log_expense(amount: float, category: str, note: str = "") -> str:
    r = tracker.log(amount, category, note, kind="expense")
    return (
        f"Logged {tracker.CURRENCY}{amount:.2f} under {category}. "
        f"{tracker.CURRENCY}{r['month_total']:.2f} spent this month "
        f"({tracker.CURRENCY}{r['category_total']:.2f} in {category})."
    )


def log_income(amount: float, category: str, note: str = "") -> str:
    r = tracker.log(amount, category, note, kind="income")
    return f"Logged {tracker.CURRENCY}{amount:.2f} income under {category}."
