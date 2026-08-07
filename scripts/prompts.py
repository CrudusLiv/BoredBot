"""Shared Claude prompts for lecture processing."""

EXTRACT_CONCEPTS = """
Extract concepts from the following lecture section. Return a list of tuples: (concept_name, definition).
Each definition should be 1-2 sentences.

Lecture section:
{lecture_text}

Return JSON:
{{"concepts": [["name", "definition"], ...]}}
"""

GENERATE_PROBLEMS = """
Generate 3 practice problems for the given learning objectives and worked examples.
Include difficulty level (Easy/Medium/Hard) and optional solution hints.

Learning objectives:
{objectives}

Worked examples:
{examples}

Return JSON:
{{
    "problems": [
        {{"difficulty": "Easy", "statement": "...", "hint": "..."}},
        ...
    ]
}}
"""

DETECT_PRIOR_LECTURES = """
Scan the lecture text for mentions of prior lectures or topics.
Return dates (YYYY-MM-DD) and topic titles where they appear.

Lecture text:
{lecture_text}

Return JSON:
{{"prior_lectures": ["2026-06-10-function-basics", "2026-06-12-loops"]}}
"""

ROADMAP_SYNTHESIS = """
Given learning objectives and practice problems, create a study roadmap with:
1. Review queue (prior topics with time estimates)
2. Practice set selection (mix of current + prior)
3. Study schedule (timeline)
4. Synthesis task

Learning objectives:
{objectives}

Current problems:
{current_problems}

Prior lectures:
{prior_lectures}

Return JSON:
{{
    "review_queue": [["topic", "15 min"], ...],
    "practice_set": [["source", "problem_statement"], ...],
    "schedule": {{"today": "Review + study", "tomorrow": "Practice", ...}},
    "synthesis_task": "..."
}}
"""
