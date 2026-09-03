"""parse_path grammar + is_denied filtering for voice/university_intake.py."""
from __future__ import annotations

from pathlib import Path

from voice.university_intake import ParsedPath, is_denied, parse_path

ROOT = Path("D:/University")


def _p(*parts: str) -> Path:
    return ROOT.joinpath(*parts)


def test_parse_assignment_degree_sem2():
    p = _p("University", "Uni Assignments", "Degree", "Sem 2", "BIT216", "brief.pdf")
    parsed = parse_path(p, ROOT)
    assert parsed == ParsedPath(
        category="assignment", program="Degree", semester=2,
        course="BIT216", subpath="brief.pdf", source=p,
    )


def test_parse_tutorial_diploma_deep_subpath():
    p = _p("University", "Uni Tutorial", "Diploma", "Sem 5", "BCS102", "week3", "lab.docx")
    parsed = parse_path(p, ROOT)
    assert parsed is not None
    assert parsed.category == "tutorial"
    assert parsed.program == "Diploma"
    assert parsed.semester == 5
    assert parsed.course == "BCS102"
    assert parsed.subpath == "week3/lab.docx"


def test_parse_rejects_file_directly_under_kind():
    p = _p("University", "Uni Assignments", "loose.pdf")
    assert parse_path(p, ROOT) is None


def test_parse_rejects_missing_sem_segment():
    p = _p("University", "Uni Assignments", "Degree", "BIT216", "brief.pdf")
    assert parse_path(p, ROOT) is None


def test_parse_rejects_outside_uni_kind():
    p = _p("University", "Uni General", "notes.pdf")
    assert parse_path(p, ROOT) is None


def test_is_denied_by_segment_any_depth():
    dl = ["Visual Studio", "intern", "Uni General"]
    ext = [".pdf", ".docx"]
    assert is_denied(_p("Visual Studio", "Calorie Counter", "Program.pdf"), dl, ext)
    assert is_denied(_p("intern", "Logbook.pdf"), dl, ext)
    assert is_denied(_p("University", "Uni Assignments", "Degree", "Sem 1", "Uni General", "x.pdf"), dl, ext)


def test_is_denied_case_insensitive_segment():
    assert is_denied(_p("university", "uni general", "x.pdf"), ["Uni General"], [".pdf"])


def test_is_denied_by_extension():
    assert is_denied(_p("University", "datamodeler.zip"), [], [".pdf", ".docx"])
    assert not is_denied(_p("University", "Uni Tutorial", "Degree", "Sem 1", "FEC100", "a.pdf"),
                         [], [".pdf", ".docx"])
