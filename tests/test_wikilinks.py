"""Section 5: wikilinks helper. Siblings = same folder + subfolders one level deep."""
from __future__ import annotations

import sys
from pathlib import Path


def _import_wikilinks():
    repo_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo_root / ".claude" / "scripts"))
    from memory import wikilinks  # type: ignore
    return wikilinks


def _write_note(p: Path, body: str = "# Title\n\nbody\n") -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")


def test_no_siblings_strips_related(tmp_path):
    wl = _import_wikilinks()
    note = tmp_path / "DIP209" / "lone.md"
    _write_note(note, "# T\n\n<!-- related:begin -->\n## Related\n- [[ghost]]\n<!-- related:end -->\n")
    wl.add_sibling_wikilinks(note)
    text = note.read_text(encoding="utf-8")
    assert "<!-- related:begin -->" not in text
    assert "[[ghost]]" not in text


def test_same_folder_siblings_linked(tmp_path):
    wl = _import_wikilinks()
    a = tmp_path / "DIP209" / "a.md"
    b = tmp_path / "DIP209" / "b.md"
    _write_note(a)
    _write_note(b)
    wl.add_sibling_wikilinks(a)
    text_a = a.read_text(encoding="utf-8")
    text_b = b.read_text(encoding="utf-8")
    assert "[[b]]" in text_a
    assert "[[a]]" in text_b  # bidirectional


def test_subfolder_siblings_one_level_deep(tmp_path):
    wl = _import_wikilinks()
    # projects/DIP209/Assessment_2/note.md should see Assessment_3/other.md
    a = tmp_path / "DIP209" / "Assessment_2" / "note.md"
    b = tmp_path / "DIP209" / "Assessment_3" / "other.md"
    _write_note(a)
    _write_note(b)
    wl.add_sibling_wikilinks(a)
    text_a = a.read_text(encoding="utf-8")
    text_b = b.read_text(encoding="utf-8")
    assert "[[other]]" in text_a
    assert "[[note]]" in text_b


def test_grandchild_not_a_sibling(tmp_path):
    """Two levels deep is NOT a sibling — keeps the graph from exploding."""
    wl = _import_wikilinks()
    a = tmp_path / "DIP209" / "a.md"
    grandchild = tmp_path / "DIP209" / "Assessment_2" / "deeper" / "z.md"
    _write_note(a)
    _write_note(grandchild)
    wl.add_sibling_wikilinks(a)
    text_a = a.read_text(encoding="utf-8")
    assert "[[z]]" not in text_a


def test_idempotent_rerun(tmp_path):
    wl = _import_wikilinks()
    a = tmp_path / "DIP209" / "a.md"
    b = tmp_path / "DIP209" / "b.md"
    _write_note(a)
    _write_note(b)
    wl.add_sibling_wikilinks(a)
    first = a.read_text(encoding="utf-8")
    wl.add_sibling_wikilinks(a)
    second = a.read_text(encoding="utf-8")
    assert first == second
    assert first.count("[[b]]") == 1


def test_self_link_skipped(tmp_path):
    wl = _import_wikilinks()
    a = tmp_path / "DIP209" / "a.md"
    _write_note(a)
    # Only one note in folder — should produce no Related block at all.
    wl.add_sibling_wikilinks(a)
    assert "[[a]]" not in a.read_text(encoding="utf-8")


def test_category_root_blocks_cross_course_links(tmp_path):
    """A note in lectures/DIP215/ must NOT link to lectures/Kotlin/."""
    wl = _import_wikilinks()
    dip215 = tmp_path / "lectures" / "DIP215" / "static_methods.md"
    kotlin = tmp_path / "lectures" / "Kotlin" / "functions.md"
    _write_note(dip215)
    _write_note(kotlin)
    wl.add_sibling_wikilinks(dip215)
    text_dip = dip215.read_text(encoding="utf-8")
    text_kt = kotlin.read_text(encoding="utf-8")
    assert "[[functions]]" not in text_dip
    assert "[[static_methods]]" not in text_kt


def test_project_assessment_links_preserved(tmp_path):
    """projects/DIP209/Assessment_2/ should still see Assessment_3/ — the
    subject folder (DIP209) is NOT a category root, so traversal allowed."""
    wl = _import_wikilinks()
    a = tmp_path / "projects" / "DIP209" / "Assessment_2" / "spec.md"
    b = tmp_path / "projects" / "DIP209" / "Assessment_3" / "report.md"
    _write_note(a)
    _write_note(b)
    wl.add_sibling_wikilinks(a)
    text_a = a.read_text(encoding="utf-8")
    text_b = b.read_text(encoding="utf-8")
    assert "[[report]]" in text_a
    assert "[[spec]]" in text_b
