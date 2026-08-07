"""Ambient notification rules: surface meaningful connections proactively."""

import json
from pathlib import Path
from typing import List, Dict, Any
from datetime import datetime, timedelta
import re

def scan_vault_state(vault_dir: Path) -> Dict[str, Any]:
    """
    Scan vault for lectures, concepts, deadlines, assignments.
    Returns a dict with all relevant metadata for rule evaluation.
    """
    state = {
        "lectures": {},
        "concepts": {},
        "deadlines": {},
        "assignments": {},
        "lectures_by_concept": {},
        "topics_to_lectures": {}
    }

    # Scan lectures
    lectures_dir = vault_dir / "lectures"
    if lectures_dir.exists():
        for lecture_file in lectures_dir.rglob("*.md"):
            if "ROADMAP" not in lecture_file.name:
                content = lecture_file.read_text()
                date_match = re.match(r"(\d{4}-\d{2}-\d{2})", lecture_file.name)
                title_match = re.search(r"^#\s+(.+?)(?:\s*\(|$)", content, re.MULTILINE)

                lecture_key = lecture_file.stem
                state["lectures"][lecture_key] = {
                    "date": date_match.group(1) if date_match else None,
                    "title": title_match.group(1) if title_match else lecture_file.stem,
                    "file": str(lecture_file)
                }

                # Extract concepts from lecture
                concepts_match = re.findall(r"\[\[([^\]]+)\]\]", content)
                for concept in concepts_match:
                    if concept not in state["lectures_by_concept"]:
                        state["lectures_by_concept"][concept] = []
                    state["lectures_by_concept"][concept].append(lecture_key)

    # Scan concepts
    concepts_dir = vault_dir / "concepts"
    if concepts_dir.exists():
        for concept_file in concepts_dir.glob("*.md"):
            content = concept_file.read_text()
            state["concepts"][concept_file.stem] = {
                "title": concept_file.stem.replace("-", " "),
                "file": str(concept_file)
            }

    # Scan deadlines (DEADLINES.md)
    deadlines_file = vault_dir / "DEADLINES.md"
    if deadlines_file.exists():
        content = deadlines_file.read_text()
        # Simple parse: extract table rows with date, title, topic
        for line in content.split("\n"):
            if "|" in line and "2026" in line:
                parts = [p.strip() for p in line.split("|")]
                if len(parts) >= 4:
                    try:
                        date_str = parts[1]
                        title = parts[2]
                        topics = parts[3]
                        state["deadlines"][date_str] = {
                            "title": title,
                            "topics": [t.strip() for t in topics.split(",")]
                        }
                    except:
                        pass

    return state

def rule_dependency_gap(state: Dict[str, Any]) -> List[Dict[str, str]]:
    """
    Rule: Deadline on topic X -> check if prerequisites are reviewed.
    Returns notifications if a prerequisite is missing.
    """
    notifications = []
    today = datetime.now().date()

    for deadline_date_str, deadline_info in state.get("deadlines", {}).items():
        try:
            deadline_date = datetime.strptime(deadline_date_str, "%Y-%m-%d").date()
        except:
            continue

        # Only check deadlines in next 2 weeks
        if not (today <= deadline_date <= today + timedelta(days=14)):
            continue

        topics = deadline_info.get("topics", [])
        for topic in topics:
            # Check if we have lectures on this topic
            lectures_on_topic = [
                key for key, lecture in state.get("lectures", {}).items()
                if topic.lower() in lecture.get("title", "").lower()
            ]

            if not lectures_on_topic:
                notifications.append({
                    "type": "dependency",
                    "rule": "dependency_gap",
                    "content": f"[dependency] {deadline_info['title']} is due {deadline_date_str}, but we haven't covered {topic} yet. Start the prerequisite lecture."
                })

    return notifications

def rule_synthesis_readiness(state: Dict[str, Any]) -> List[Dict[str, str]]:
    """
    Rule: Concept appears in 3+ lectures -> suggest synthesis.
    Returns notifications when a concept is well-covered.
    """
    notifications = []
    threshold = 3

    for concept, lectures in state.get("lectures_by_concept", {}).items():
        if len(lectures) >= threshold:
            notifications.append({
                "type": "synthesis",
                "rule": "synthesis_readiness",
                "content": f"[synthesis] You've encountered '{concept.replace('-', ' ')}' in {len(lectures)} lectures. Ready for a synthesis problem? Consider reviewing and connecting them."
            })

    return notifications

def rule_assignment_prep(state: Dict[str, Any]) -> List[Dict[str, str]]:
    """
    Rule: Assignment mentions topic X -> check if lecture on X is completed.
    Returns notifications if assignment prep is missing.
    """
    notifications = []
    # Placeholder: this would scan assignment files for topics and cross-ref lectures
    return notifications

def rule_knowledge_gap(state: Dict[str, Any]) -> List[Dict[str, str]]:
    """
    Rule: Concept appears in 3+ lectures but has few practice problems completed.
    Returns notifications for focused review.
    """
    notifications = []
    # Placeholder: would check practice problem completion
    return notifications

def collect_notifications(state: Dict[str, Any]) -> List[Dict[str, str]]:
    """
    Run all rules and collect notifications.
    """
    all_notifications = []

    all_notifications.extend(rule_dependency_gap(state))
    all_notifications.extend(rule_synthesis_readiness(state))
    all_notifications.extend(rule_assignment_prep(state))
    all_notifications.extend(rule_knowledge_gap(state))

    return all_notifications
