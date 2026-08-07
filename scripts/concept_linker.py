"""Auto-wire concepts from lectures to concept wiki."""

import json
import re
from pathlib import Path
from typing import List, Tuple
import anthropic

from scripts.prompts import EXTRACT_CONCEPTS, DETECT_PRIOR_LECTURES

def slug_from_name(name: str) -> str:
    """Convert 'Stack Frame' to 'stack-frame'."""
    return name.lower().replace(" ", "-").replace("_", "-")

def extract_concepts_from_lecture(lecture_text: str) -> List[Tuple[str, str]]:
    """
    Extract concept names and definitions from lecture text.
    Returns list of (name, definition) tuples.
    """
    client = anthropic.Anthropic()

    response = client.messages.create(
        model="claude-3-5-haiku-20241022",
        max_tokens=1024,
        messages=[
            {
                "role": "user",
                "content": EXTRACT_CONCEPTS.format(lecture_text=lecture_text)
            }
        ]
    )

    try:
        result = json.loads(response.content[0].text)
        return [tuple(c) for c in result.get("concepts", [])]
    except (json.JSONDecodeError, KeyError, IndexError):
        return []

def create_or_update_concept_stub(
    concepts_dir: Path,
    concept_name: str,
    definition: str,
    lecture_ref: str
) -> None:
    """
    Create a new concept stub or update existing one with lecture backlink.
    """
    slug = slug_from_name(concept_name)
    concept_file = concepts_dir / f"{slug}.md"

    if concept_file.exists():
        # Update: add lecture to "Reinforced in" section
        content = concept_file.read_text()
        if f"[[{lecture_ref}]]" not in content:
            # Append to Reinforced in section or create it
            if "## Reinforced in" in content:
                content = content.replace(
                    "## Reinforced in",
                    f"## Reinforced in\n- [[{lecture_ref}]]",
                    1
                )
            else:
                content += f"\n\n## Reinforced in\n- [[{lecture_ref}]]"
            concept_file.write_text(content)
    else:
        # Create new stub
        content = f"""# {concept_name}

{definition}

## Introduced in
- [[{lecture_ref}]]
"""
        concept_file.write_text(content)

def link_concepts_in_lecture(lecture_text: str, concept_names: List[str]) -> str:
    """
    Replace bare concept names in lecture with wikilinks.
    E.g., 'Stack Frame' -> '[[stack-frame]]'
    """
    result = lecture_text
    for name in concept_names:
        slug = slug_from_name(name)
        # Simple word boundary replacement
        pattern = r"\b" + re.escape(name) + r"\b"
        replacement = f"[[{slug}]]"
        result = re.sub(pattern, replacement, result)
    return result

def detect_prior_lectures(lecture_text: str, course_name: str) -> List[str]:
    """
    Detect references to prior lectures in lecture text.
    Returns list of prior lecture dates (YYYY-MM-DD-topic format).
    """
    client = anthropic.Anthropic()

    response = client.messages.create(
        model="claude-3-5-haiku-20241022",
        max_tokens=512,
        messages=[
            {
                "role": "user",
                "content": DETECT_PRIOR_LECTURES.format(lecture_text=lecture_text)
            }
        ]
    )

    try:
        result = json.loads(response.content[0].text)
        return result.get("prior_lectures", [])
    except (json.JSONDecodeError, KeyError):
        return []

def process_lecture_concepts(
    lecture_file: Path,
    vault_dir: Path
) -> None:
    """
    Main entry point: process a lecture file for concept linking.
    1. Extract concepts from lecture
    2. Create/update concept stubs
    3. Auto-wikilink concepts in lecture
    4. Detect and link prior lectures (bidirectional)
    """
    lecture_text = lecture_file.read_text()
    concepts_dir = vault_dir / "concepts"
    concepts_dir.mkdir(exist_ok=True)

    # Extract and link concepts
    concept_tuples = extract_concepts_from_lecture(lecture_text)
    for concept_name, definition in concept_tuples:
        lecture_ref = lecture_file.stem  # e.g., "2026-06-16-recursion"
        create_or_update_concept_stub(concepts_dir, concept_name, definition, lecture_ref)

    # Wikilink concepts in the lecture
    concept_names = [name for name, _ in concept_tuples]
    linked_text = link_concepts_in_lecture(lecture_text, concept_names)

    # Detect prior lectures and create bidirectional links
    prior_refs = detect_prior_lectures(lecture_text, lecture_file.parent.name)
    for prior_ref in prior_refs:
        if prior_ref not in linked_text:
            linked_text += f"\n\n## References\n- Prior: [[{prior_ref}]]"

        # Add reciprocal link to prior lecture
        lectures_dir = vault_dir / "lectures"
        prior_file = None
        for lecture in lectures_dir.rglob(f"{prior_ref}.md"):
            prior_file = lecture
            break

        if prior_file and prior_file.exists():
            prior_content = prior_file.read_text()
            current_ref = lecture_file.stem
            if f"[[{current_ref}]]" not in prior_content:
                prior_content += f"\n\nSee also: [[{current_ref}]]"
                prior_file.write_text(prior_content)

    # Write updated lecture with wikilinks
    lecture_file.write_text(linked_text)
