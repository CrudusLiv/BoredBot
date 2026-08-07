"""Integration test: full lecture intake flow (extract → concepts → roadmap)."""

import pytest
import json
from pathlib import Path
from unittest.mock import Mock, patch
from scripts.concept_linker import process_lecture_concepts
from scripts.roadmap_generator import generate_roadmap_file


def test_full_lecture_intake_flow(tmp_path):
    """
    Integration test: lecture lands → extract concepts → create stubs → wikilink → generate roadmap

    This end-to-end test verifies the complete pipeline:
    1. Lecture file with key concepts and problems
    2. Extract concepts via process_lecture_concepts()
    3. Verify concept stub files are created
    4. Verify wikilinks are added to lecture
    5. Generate roadmap and verify content
    """
    # Setup directory structure
    vault_dir = tmp_path / "Memory"
    vault_dir.mkdir()

    lectures_dir = vault_dir / "lectures" / "CS101"
    lectures_dir.mkdir(parents=True)

    (vault_dir / "inbox").mkdir()
    (vault_dir / "inbox" / "_processed").mkdir()

    concepts_dir = vault_dir / "concepts"
    concepts_dir.mkdir()

    # Create a sample lecture file with content
    lecture_file = lectures_dir / "2026-06-16-recursion.md"
    lecture_text = """# Recursion Theory

## Summary
Recursion is a fundamental technique in computer science that allows functions to call themselves.

## Learning Objectives
- Understand the call stack and how function calls work
- Apply recursion to solve problems
- Master the concept of base cases

## Key Concepts
- **Stack Frame**: An activation record that stores local variables and return address
- **Base Case**: The termination condition that stops recursion
- **Recursive Call**: A function calling itself with modified parameters

## Worked Examples
Example of recursive function computing factorial.

## Practice Problems
- Easy: Sum a list recursively
- Medium: Binary search using recursion
- Hard: Tree traversal with depth tracking
"""
    lecture_file.write_text(lecture_text)

    # Mock the Anthropic API for concept extraction
    mock_response_concepts = Mock()
    mock_response_concepts.content = [Mock(text=json.dumps({
        "concepts": [
            ["Stack Frame", "An activation record that stores local variables and return address"],
            ["Base Case", "The termination condition that stops recursion"],
            ["Recursive Call", "A function calling itself with modified parameters"]
        ]
    }))]

    mock_response_prior = Mock()
    mock_response_prior.content = [Mock(text=json.dumps({
        "prior_lectures": []
    }))]

    with patch("anthropic.Anthropic") as mock_anthropic:
        mock_client = Mock()
        mock_anthropic.return_value = mock_client

        # Setup response side effects: first for concept extraction, second for prior lectures
        mock_client.messages.create.side_effect = [
            mock_response_concepts,
            mock_response_prior
        ]

        # Process lecture concepts
        process_lecture_concepts(lecture_file, vault_dir)

    # Verify concept stub files were created
    concept_files = list(concepts_dir.glob("*.md"))
    assert len(concept_files) == 3, f"Expected 3 concept files, got {len(concept_files)}"

    # Verify specific concept files exist
    assert (concepts_dir / "stack-frame.md").exists()
    assert (concepts_dir / "base-case.md").exists()
    assert (concepts_dir / "recursive-call.md").exists()

    # Verify concept content
    stack_frame_content = (concepts_dir / "stack-frame.md").read_text()
    assert "Stack Frame" in stack_frame_content
    assert "activation record" in stack_frame_content
    assert "2026-06-16-recursion" in stack_frame_content

    # Verify wikilinks were added to lecture
    lecture_content = lecture_file.read_text()
    assert "[[stack-frame]]" in lecture_content
    assert "[[base-case]]" in lecture_content
    assert "[[recursive-call]]" in lecture_content

    # Now generate roadmap
    lecture_data = {
        "title": "Recursion Theory",
        "objectives": [
            "Understand the call stack and how function calls work",
            "Apply recursion to solve problems",
            "Master the concept of base cases"
        ],
        "problems": [
            {"difficulty": "Easy", "statement": "Sum a list recursively"},
            {"difficulty": "Medium", "statement": "Binary search using recursion"},
            {"difficulty": "Hard", "statement": "Tree traversal with depth tracking"}
        ],
        "prior_lectures": []
    }

    # Mock roadmap generation
    mock_response_roadmap = Mock()
    mock_response_roadmap.content = [Mock(text=json.dumps({
        "review_queue": [["Function Basics", "15 min"]],
        "practice_set": [
            {"difficulty": "Easy", "statement": "Sum a list recursively"},
            {"difficulty": "Medium", "statement": "Binary search using recursion"}
        ],
        "schedule": {
            "today": "Review function basics, then study recursion",
            "tomorrow": "Practice easy and medium problems"
        },
        "synthesis_task": "Implement tree traversal with recursion"
    }))]

    with patch("anthropic.Anthropic") as mock_anthropic:
        mock_client = Mock()
        mock_anthropic.return_value = mock_client
        mock_client.messages.create.return_value = mock_response_roadmap

        # Generate roadmap
        roadmap_file = generate_roadmap_file(lecture_file, lecture_data)

    # Verify roadmap file exists
    assert roadmap_file.exists()
    assert roadmap_file.name == "2026-06-16-recursion-ROADMAP.md"
    assert roadmap_file.parent == lectures_dir

    # Verify roadmap content
    roadmap_content = roadmap_file.read_text()
    assert "# Study Roadmap" in roadmap_content
    assert "Recursion Theory" in roadmap_content
    assert "Sum a list recursively" in roadmap_content
    assert "Binary search using recursion" in roadmap_content
    assert "Easy" in roadmap_content
    assert "Medium" in roadmap_content
    assert "Synthesis" in roadmap_content
    assert "Function Basics" in roadmap_content


def test_lecture_flow_with_prior_lectures(tmp_path):
    """
    Test the full flow including detection and linking of prior lectures.
    """
    vault_dir = tmp_path / "Memory"
    vault_dir.mkdir()

    lectures_dir = vault_dir / "lectures" / "CS101"
    lectures_dir.mkdir(parents=True)

    concepts_dir = vault_dir / "concepts"
    concepts_dir.mkdir()

    # Create a prior lecture
    prior_file = lectures_dir / "2026-06-10-function-basics.md"
    prior_file.write_text("# Function Basics\n\nFunctions are reusable code blocks.")

    # Create current lecture that references prior lecture
    lecture_file = lectures_dir / "2026-06-16-recursion.md"
    lecture_text = """# Recursion Theory

Building on function basics from earlier, recursion is when a function calls itself.

## Key Concepts
- **Tail Recursion**: Optimization when recursive call is the last operation
"""
    lecture_file.write_text(lecture_text)

    # Mock API responses
    mock_response_concepts = Mock()
    mock_response_concepts.content = [Mock(text=json.dumps({
        "concepts": [
            ["Tail Recursion", "Optimization when recursive call is the last operation"]
        ]
    }))]

    mock_response_prior = Mock()
    mock_response_prior.content = [Mock(text=json.dumps({
        "prior_lectures": ["2026-06-10-function-basics"]
    }))]

    with patch("anthropic.Anthropic") as mock_anthropic:
        mock_client = Mock()
        mock_anthropic.return_value = mock_client
        mock_client.messages.create.side_effect = [
            mock_response_concepts,
            mock_response_prior
        ]

        process_lecture_concepts(lecture_file, vault_dir)

    # Verify wikilink to prior lecture was added
    lecture_content = lecture_file.read_text()
    assert "[[2026-06-10-function-basics]]" in lecture_content

    # Verify prior lecture has reciprocal link
    prior_content = prior_file.read_text()
    assert "[[2026-06-16-recursion]]" in prior_content

    # Verify concept stub was created
    assert (concepts_dir / "tail-recursion.md").exists()


def test_integration_concept_stubs_updated_on_second_lecture(tmp_path):
    """
    Test that when a second lecture references the same concept,
    the concept stub is updated (not recreated).
    """
    vault_dir = tmp_path / "Memory"
    vault_dir.mkdir()

    lectures_dir = vault_dir / "lectures" / "CS101"
    lectures_dir.mkdir(parents=True)

    concepts_dir = vault_dir / "concepts"
    concepts_dir.mkdir()

    # First lecture
    lecture1_file = lectures_dir / "2026-06-10-functions.md"
    lecture1_file.write_text("""# Functions

## Key Concepts
- **Return Value**: The output of a function
""")

    # Second lecture that also mentions Return Value
    lecture2_file = lectures_dir / "2026-06-17-advanced-functions.md"
    lecture2_file.write_text("""# Advanced Functions

Building on return values, we can now...

## Key Concepts
- **Return Value**: Data returned from function execution
""")

    # Mock API responses for first lecture
    mock_response_1 = Mock()
    mock_response_1.content = [Mock(text=json.dumps({
        "concepts": [["Return Value", "The output of a function"]]
    }))]

    mock_response_prior_1 = Mock()
    mock_response_prior_1.content = [Mock(text=json.dumps({"prior_lectures": []}))]

    with patch("anthropic.Anthropic") as mock_anthropic:
        mock_client = Mock()
        mock_anthropic.return_value = mock_client
        mock_client.messages.create.side_effect = [
            mock_response_1,
            mock_response_prior_1
        ]
        process_lecture_concepts(lecture1_file, vault_dir)

    # Verify concept stub created
    concept_file = concepts_dir / "return-value.md"
    assert concept_file.exists()
    content_after_first = concept_file.read_text()
    assert "2026-06-10-functions" in content_after_first

    # Now process second lecture
    mock_response_2 = Mock()
    mock_response_2.content = [Mock(text=json.dumps({
        "concepts": [["Return Value", "Data returned from function execution"]]
    }))]

    mock_response_prior_2 = Mock()
    mock_response_prior_2.content = [Mock(text=json.dumps({"prior_lectures": []}))]

    with patch("anthropic.Anthropic") as mock_anthropic:
        mock_client = Mock()
        mock_anthropic.return_value = mock_client
        mock_client.messages.create.side_effect = [
            mock_response_2,
            mock_response_prior_2
        ]
        process_lecture_concepts(lecture2_file, vault_dir)

    # Verify concept stub was updated (not recreated)
    content_after_second = concept_file.read_text()
    assert "2026-06-10-functions" in content_after_second
    assert "2026-06-17-advanced-functions" in content_after_second
    assert "## Reinforced in" in content_after_second
