"""Agent registry — metadata for each of the 6 study agents."""
from __future__ import annotations

AGENTS: dict[str, dict] = {
    "deadline_tracker": {
        "emoji": "📅",
        "label": "Deadline Tracker",
        "description": "Scans vault for upcoming deadlines",
    },
    "concept_explainer": {
        "emoji": "🧠",
        "label": "Concept Explainer",
        "description": "Explains topics using your lecture notes",
    },
    "quiz_generator": {
        "emoji": "📝",
        "label": "Quiz Generator",
        "description": "Generates Q&A flashcards from lecture notes",
    },
    "study_planner": {
        "emoji": "📆",
        "label": "Study Planner",
        "description": "Plans study sessions based on schedule and deadlines",
    },
    "progress_monitor": {
        "emoji": "📊",
        "label": "Progress Monitor",
        "description": "Weekly summary of habits and lecture completion",
    },
    "research_synth": {
        "emoji": "🔬",
        "label": "Research Synth",
        "description": "Synthesises all vault notes on a topic",
    },
}
