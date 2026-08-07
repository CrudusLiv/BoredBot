import pytest
import json
from pathlib import Path
from scripts.concept_linker import extract_concepts_from_lecture, link_concepts_in_lecture

def test_extract_concepts():
    """Test extracting concepts from lecture text."""
    lecture_text = """
## Key Concepts
- **Stack Frame**: An activation record on the call stack
- **Base Case**: The condition that terminates recursion
"""
    concepts = extract_concepts_from_lecture(lecture_text)
    assert len(concepts) == 2
    assert concepts[0] == ("Stack Frame", "An activation record on the call stack")
    assert concepts[1] == ("Base Case", "The condition that terminates recursion")

def test_create_concept_stub():
    """Test creating a concept stub file."""
    from pathlib import Path
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        concepts_dir = Path(tmpdir) / "concepts"
        concepts_dir.mkdir()

        from scripts.concept_linker import create_or_update_concept_stub
        concept_name = "Stack Frame"
        definition = "An activation record on the call stack"
        lecture_ref = "2026-06-16-recursion"

        create_or_update_concept_stub(
            concepts_dir=concepts_dir,
            concept_name=concept_name,
            definition=definition,
            lecture_ref=lecture_ref
        )

        concept_file = concepts_dir / "stack-frame.md"
        assert concept_file.exists()
        content = concept_file.read_text()
        assert "Stack Frame" in content
        assert "An activation record on the call stack" in content
        assert "2026-06-16-recursion" in content

def test_wikilink_concepts_in_lecture():
    """Test that concepts in lecture text become wikilinks."""
    lecture_text = "Stack Frame is important in recursion. A Base Case stops recursion."
    concepts = ["Stack Frame", "Base Case"]

    linked = link_concepts_in_lecture(lecture_text, concepts)
    assert "[[stack-frame]]" in linked
    assert "[[base-case]]" in linked
