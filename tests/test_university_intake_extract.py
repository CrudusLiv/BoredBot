# tests/test_university_intake_extract.py
"""extract_text dispatch + graceful degradation for voice/university_intake.py."""
from __future__ import annotations

import pytest

from voice import university_intake as ui


def test_txt_roundtrip(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("Assignment brief\nDue 15/10/2026\n", encoding="utf-8")
    text, ok, err = ui.extract_text(f)
    assert ok is True and err is None
    assert "Assignment brief" in text


def test_md_treated_as_text(tmp_path):
    f = tmp_path / "a.md"
    f.write_text("# Heading\nbody", encoding="utf-8")
    text, ok, err = ui.extract_text(f)
    assert ok is True and err is None
    assert "Heading" in text


def test_unknown_extension_returns_empty(tmp_path):
    f = tmp_path / "a.doc"          # legacy binary, no pure-python extractor
    f.write_bytes(b"\xd0\xcf\x11\xe0garbage")
    assert ui.extract_text(f) == ("", False, None)


def test_pdf_dispatches_to_extractor(tmp_path, monkeypatch):
    f = tmp_path / "a.pdf"
    f.write_bytes(b"%PDF-1.4 fake")
    monkeypatch.setattr(ui, "_extract_pdf", lambda p: "PDF BODY TEXT")
    assert ui.extract_text(f) == ("PDF BODY TEXT", True, None)


def test_extractor_exception_is_reported(tmp_path, monkeypatch):
    f = tmp_path / "a.pdf"
    f.write_bytes(b"%PDF-1.4 fake")
    def boom(p):
        raise RuntimeError("corrupt")
    monkeypatch.setattr(ui, "_extract_pdf", boom)
    text, ok, err = ui.extract_text(f)
    assert (text, ok) == ("", False)
    assert err is not None and "corrupt" in err


def test_docx_happy_path(tmp_path):
    docx = pytest.importorskip("docx")
    d = docx.Document()
    d.add_paragraph("Coursework body paragraph")
    f = tmp_path / "a.docx"
    d.save(f)
    text, ok, err = ui.extract_text(f)
    assert ok is True and err is None
    assert "Coursework body paragraph" in text


def test_pptx_happy_path(tmp_path):
    pptx = pytest.importorskip("pptx")
    prs = pptx.Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[5])
    slide.shapes.title.text = "Slide Title Text"
    f = tmp_path / "a.pptx"
    prs.save(f)
    text, ok, err = ui.extract_text(f)
    assert ok is True and err is None
    assert "Slide Title Text" in text
