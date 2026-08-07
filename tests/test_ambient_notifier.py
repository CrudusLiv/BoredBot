import pytest
from pathlib import Path
from scripts.ambient_notifier import (
    rule_dependency_gap,
    rule_synthesis_readiness,
    rule_assignment_prep,
    collect_notifications
)

def test_dependency_gap_rule():
    """Test detecting when prerequisites are missing."""
    vault_state = {
        "deadlines": {
            "2026-06-20": {"title": "Data Structures Assignment", "topics": ["graph-theory"]}
        },
        "lectures_completed": ["recursion", "arrays"],
        "topics_to_lectures": {
            "graph-theory": ["2026-06-15-graphs"],
            "recursion": ["2026-06-16-recursion"]
        },
        "lectures": {}
    }

    notifications = rule_dependency_gap(vault_state)
    assert len(notifications) > 0
    assert "graph-theory" in notifications[0]["content"].lower()

def test_synthesis_readiness_rule():
    """Test detecting when a concept is ready for synthesis."""
    vault_state = {
        "lectures_by_concept": {
            "stack-frame": [
                "2026-06-16-recursion",
                "2026-06-18-tree-traversal",
                "2026-06-20-dynamic-programming"
            ]
        }
    }

    notifications = rule_synthesis_readiness(vault_state)
    assert len(notifications) > 0
    assert "stack frame" in notifications[0]["content"].lower()

def test_collect_notifications():
    """Test collecting all notifications from vault."""
    vault_state = {
        "deadlines": {},
        "lectures_completed": [],
        "lectures_by_concept": {}
    }

    notifications = collect_notifications(vault_state)
    assert isinstance(notifications, list)
