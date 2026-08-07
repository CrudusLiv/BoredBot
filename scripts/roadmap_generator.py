"""Generate study roadmaps from lectures."""

import json
from pathlib import Path
from typing import Dict, List, Any
import anthropic

from scripts.prompts import ROADMAP_SYNTHESIS

def build_roadmap_structure(lecture_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Build a roadmap structure using Claude.
    Input: lecture title, objectives, problems, prior lectures
    Output: roadmap structure with review queue, practice set, schedule, synthesis task
    """
    client = anthropic.Anthropic()

    response = client.messages.create(
        model="claude-3-5-haiku-20241022",
        max_tokens=1024,
        messages=[
            {
                "role": "user",
                "content": ROADMAP_SYNTHESIS.format(
                    objectives="\n".join(lecture_data.get("objectives", [])),
                    current_problems="\n".join([
                        f"- {p['difficulty']}: {p['statement']}"
                        for p in lecture_data.get("problems", [])
                    ]),
                    prior_lectures="\n".join(lecture_data.get("prior_lectures", []))
                )
            }
        ]
    )

    try:
        result = json.loads(response.content[0].text)
        return {
            "title": lecture_data.get("title"),
            "objectives": lecture_data.get("objectives", []),
            "review_queue": result.get("review_queue", []),
            "practice_set": result.get("practice_set", []),
            "schedule": result.get("schedule", {}),
            "synthesis_task": result.get("synthesis_task", "")
        }
    except (json.JSONDecodeError, KeyError):
        return {
            "title": lecture_data.get("title"),
            "review_queue": [],
            "practice_set": lecture_data.get("problems", []),
            "schedule": {},
            "synthesis_task": "Review lecture and practice problems"
        }

def format_roadmap_markdown(roadmap: Dict[str, Any]) -> str:
    """Format a roadmap structure as markdown."""
    lines = [
        f"# Study Roadmap: {roadmap.get('title', 'Untitled')}",
        "",
        "## Recommended Study Path",
        ""
    ]

    # Review queue
    step = 1
    for topic, duration in roadmap.get("review_queue", []):
        lines.append(f"{step}. **Review**: {topic} ({duration})")
        step += 1

    lines.append(f"{step}. **Study**: Current lecture ({roadmap.get('study_time', '40 min')})")
    step += 1

    lines.append(f"{step}. **Practice**: Problem set below ({roadmap.get('practice_time', '30 min')})")
    step += 1

    lines.append(f"{step}. **Synthesis**: {roadmap.get('synthesis_task', 'Integrate concepts')} (20 min)")

    lines.append("")
    lines.append("## Practice Problems")
    lines.append("")

    for problem in roadmap.get("practice_set", []):
        difficulty = problem.get("difficulty", "Medium")
        statement = problem.get("statement", "")
        lines.append(f"- **{difficulty}** - {statement}")

    lines.append("")
    lines.append("## Study Schedule")
    lines.append("")

    for day, task in roadmap.get("schedule", {}).items():
        lines.append(f"- **{day.title()}**: {task}")

    return "\n".join(lines)

def generate_roadmap_file(
    lecture_file: Path,
    lecture_data: Dict[str, Any]
) -> Path:
    """
    Generate a roadmap file paired with a lecture.
    Input: path to lecture note
    Output: path to roadmap file (same dir, suffixed with -ROADMAP)
    """
    roadmap_structure = build_roadmap_structure(lecture_data)
    roadmap_markdown = format_roadmap_markdown(roadmap_structure)

    # Create roadmap file name: 2026-06-16-recursion.md -> 2026-06-16-recursion-ROADMAP.md
    roadmap_file = lecture_file.parent / f"{lecture_file.stem}-ROADMAP.md"
    roadmap_file.write_text(roadmap_markdown)

    return roadmap_file
