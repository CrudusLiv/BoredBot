"""Integration test: full OCR pipeline (extract images → run OCR → merge text)."""

import pytest
from pathlib import Path
from scripts.ocr_processor import extract_slide_images, run_ocr_on_image, merge_text


def test_full_ocr_pipeline():
    """Integration test: full OCR pipeline on a sample lecture."""
    test_lecture_path = Path("tests/fixtures/sample_lecture_with_images.pdf")

    if not test_lecture_path.exists():
        pytest.skip("Test fixture not available")

    images = extract_slide_images(pdf_path=test_lecture_path, pptx_path=None)
    assert len(images) > 0

    ocr_text, confidence, error = run_ocr_on_image(images[0])

    if error:
        assert ocr_text == ""
    else:
        assert len(ocr_text) > 0
        assert 0 <= confidence <= 1

    original = "Some original text"
    merged, used_ocr = merge_text(original, ocr_text)

    assert isinstance(merged, str)
    assert isinstance(used_ocr, bool)


def test_ocr_pipeline_with_fixture_pdf():
    """Integration test using the existing PDF fixture."""
    test_lecture_path = Path("tests/fixtures/sample_lecture.pdf")

    if not test_lecture_path.exists():
        pytest.skip("Test fixture not available")

    images = extract_slide_images(pdf_path=test_lecture_path, pptx_path=None)

    # PDF extraction may return empty if poppler not installed — that's acceptable
    if not images:
        pytest.skip("PDF image extraction not available (poppler not installed)")

    assert all(hasattr(img, "size") for img in images)

    ocr_text, confidence, error = run_ocr_on_image(images[0])
    assert isinstance(ocr_text, str)
    assert isinstance(confidence, float)
    # error is either None (success) or a string (failure)
    assert error is None or isinstance(error, str)

    original = "test original text"
    merged, used_ocr = merge_text(original, ocr_text)
    assert isinstance(merged, str)
    assert isinstance(used_ocr, bool)


def test_ocr_pipeline_with_fixture_pptx():
    """Integration test using the existing PPTX fixture."""
    test_lecture_path = Path("tests/fixtures/sample_lecture.pptx")

    if not test_lecture_path.exists():
        pytest.skip("Test fixture not available")

    images = extract_slide_images(pdf_path=None, pptx_path=test_lecture_path)
    assert len(images) > 0

    for i, image in enumerate(images):
        ocr_text, confidence, error = run_ocr_on_image(image)
        assert isinstance(ocr_text, str)
        assert isinstance(confidence, float)
        assert 0.0 <= confidence <= 1.0

        original = f"Original slide {i + 1} text"
        merged, used_ocr = merge_text(original, ocr_text)
        assert isinstance(merged, str)
        assert merged in (original, ocr_text)
