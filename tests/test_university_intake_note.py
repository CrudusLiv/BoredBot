"""slugify / summarise / note_for for voice/university_intake.py."""
from __future__ import annotations

from pathlib import Path

from voice.university_intake import ParsedPath, note_for, slugify, summarise

PARSED = ParsedPath(
    category="assignment", program="Degree", semester=2, course="BIT216",
    subpath="week 3/Final Brief.pdf", source=Path("D:/University/x/Final Brief.pdf"),
)


def test_slugify():
    assert slugify("week 3/Final Brief.pdf") == "week-3-final-brief"
    assert slugify("A  B__C.docx") == "a-b-c"


def test_summarise_truncates_to_60_words():
    body = " ".join(f"w{i}" for i in range(200))
    out = summarise(body, PARSED)
    assert len(out.split()) <= 60
    assert out.startswith("w0 w1 w2")


def test_summarise_fallback_when_empty():
    out = summarise("", PARSED)
    assert "BIT216" in out and "no extractable text" in out.lower()


def test_note_for_per_file_structure():
    relpath, md = note_for(PARSED, "Body text here.", truncated=False, mode="per-file")
    assert relpath == "coursework/bit216/week-3-final-brief.md"
    assert md.startswith("---\n")
    assert "course: BIT216" in md
    assert "category: assignment" in md
    assert "semester: 2" in md
    assert "truncated: false" in md
    assert "[[bit216]]" in md
    assert md.rstrip().endswith("Body text here.")


def test_note_for_marks_truncated():
    _, md = note_for(PARSED, "x", truncated=True, mode="per-file")
    assert "truncated: true" in md


def test_note_for_rollup_relpath_and_section():
    relpath, md = note_for(PARSED, "Body.", truncated=False, mode="rollup")
    assert relpath == "coursework/bit216.md"
    assert md.lstrip().startswith("## ")
    assert "week 3/Final Brief.pdf" in md
