import pytest
import json
from pathlib import Path
from unittest.mock import Mock, patch
from scripts.roadmap_generator import build_roadmap_structure, format_roadmap_markdown

def test_build_roadmap_structure():
    """Test building a roadmap from lecture data."""
    lecture_data = {
        "title": "Recursion Theory",
        "objectives": [
            "Understand the call stack",
            "Apply recursion to solve tree traversal"
        ],
        "problems": [
            {"difficulty": "Easy", "statement": "Sum of list"},
            {"difficulty": "Medium", "statement": "Binary search"}
        ],
        "prior_lectures": ["2026-06-10-function-basics"]
    }

    # Mock the Anthropic API response
    mock_response = Mock()
    mock_response.content = [Mock(text=json.dumps({
        "review_queue": [["Function Basics", "15 min"]],
        "practice_set": [["Source 1", "Problem 1"]],
        "schedule": {"today": "Review + study", "tomorrow": "Practice"},
        "synthesis_task": "Implement tree traversal"
    }))]

    with patch("anthropic.Anthropic") as mock_anthropic:
        mock_client = Mock()
        mock_anthropic.return_value = mock_client
        mock_client.messages.create.return_value = mock_response

        roadmap = build_roadmap_structure(lecture_data)

    assert roadmap["title"] == "Recursion Theory"
    assert len(roadmap["review_queue"]) > 0
    assert len(roadmap["practice_set"]) > 0
    assert "schedule" in roadmap

def test_format_roadmap():
    """Test formatting roadmap as markdown."""
    roadmap = {
        "title": "Recursion Theory",
        "objectives": ["Understand call stack"],
        "review_queue": [["Function Basics", "15 min"]],
        "practice_set": [
            {"difficulty": "Easy", "statement": "Sum of list"},
            {"difficulty": "Medium", "statement": "Binary search"}
        ],
        "schedule": {
            "today": "Review + study",
            "tomorrow": "Practice problems"
        },
        "synthesis_task": "Implement tree traversal"
    }

    markdown = format_roadmap_markdown(roadmap)
    assert "# Study Roadmap" in markdown
    assert "Recursion Theory" in markdown
    assert "Easy" in markdown
    assert "Synthesis" in markdown
