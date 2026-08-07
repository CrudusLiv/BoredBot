"""OCR processing for image-only slides in lectures."""

from pathlib import Path
from typing import Any, List, Optional, Tuple
from PIL import Image
import logging
import numpy as np

logger = logging.getLogger(__name__)

# Global OCR reader cache
_ocr_reader = None


def _get_ocr_reader():
    """Get or initialize cached EasyOCR reader.

    Returns:
        easyocr.Reader instance or None if import fails
    """
    global _ocr_reader
    if _ocr_reader is None:
        try:
            import easyocr
            _ocr_reader = easyocr.Reader(['en'], gpu=False, verbose=False)
        except ImportError:
            logger.error("easyocr not installed. Install with: pip install easyocr")
            return None
    return _ocr_reader


def extract_slide_images(
    pdf_path: Optional[Path] = None,
    pptx_path: Optional[Path] = None
) -> List[Image.Image]:
    """
    Extract images from PDF or PPTX file.

    Args:
        pdf_path: Path to PDF file (mutually exclusive with pptx_path)
        pptx_path: Path to PPTX file (mutually exclusive with pdf_path)

    Returns:
        List of PIL Images, one per slide, in order. Returns empty list if neither
        path is provided or if extraction fails.
    """
    if not pdf_path and not pptx_path:
        return []

    if pdf_path:
        return _extract_from_pdf(pdf_path)
    else:
        return _extract_from_pptx(pptx_path)


def _extract_from_pdf(pdf_path: Path) -> List[Image.Image]:
    """Extract images from PDF file."""
    try:
        from pdf2image import convert_from_path
    except ImportError:
        logger.error("pdf2image not installed. Install with: pip install pdf2image")
        return []

    try:
        images = convert_from_path(str(pdf_path), dpi=200)
        return images
    except Exception as e:
        logger.error(f"Failed to extract images from PDF {pdf_path}: {e}")
        return []


def _extract_from_pptx(pptx_path: Path) -> List[Image.Image]:
    """Extract slide images from PPTX file."""
    try:
        from pptx import Presentation
    except ImportError:
        logger.error("python-pptx not installed. Install with: pip install python-pptx")
        return []

    try:
        prs = Presentation(str(pptx_path))
        images = []

        for slide_idx, slide in enumerate(prs.slides, 1):
            slide_image = _render_slide_to_image(slide, slide_idx)
            if slide_image:
                images.append(slide_image)

        return images
    except Exception as e:
        logger.error(f"Failed to extract images from PPTX {pptx_path}: {e}")
        return []


def _render_slide_to_image(slide: Any, slide_idx: int) -> Optional[Image.Image]:
    """Render a PPTX slide to a PIL Image.

    Args:
        slide: pptx.util.Slide object to render
        slide_idx: Index of the slide (1-based)

    Returns:
        PIL Image or None if rendering fails
    """
    # TODO: implement actual slide rendering (extract shapes, text, images from slide)
    # Create a blank image for the slide (standard 16:9 aspect ratio)
    width, height = 1280, 720
    image = Image.new('RGB', (width, height), color='white')

    return image


def run_ocr_on_image(image: Optional[Image.Image]) -> Tuple[str, float, Optional[str]]:
    """
    Run EasyOCR on a slide image to extract text.

    Args:
        image: PIL Image of slide to process

    Returns:
        Tuple of (extracted_text, confidence_score, error_message)
        - extracted_text: string of recognized text (empty string if error or no text found)
        - confidence_score: float 0-1 indicating average confidence across all detected text
        - error_message: string describing error if one occurred, None otherwise
    """
    if image is None:
        return "", 0.0, "Image is None"

    # Get cached reader instance
    reader = _get_ocr_reader()
    if reader is None:
        return "", 0.0, "easyocr not installed"

    try:
        # Convert PIL Image to numpy array for easyocr
        image_array = np.asarray(image)

        # Run OCR
        results = reader.readtext(image_array, detail=1)

        # Extract text and calculate average confidence
        texts = []
        confidences = []

        for (bbox, text, conf) in results:
            texts.append(text)
            confidences.append(conf)

        extracted_text = " ".join(texts)
        avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0

        return extracted_text, avg_confidence, None

    except (ValueError, RuntimeError, TypeError, OSError) as e:
        logger.error(f"OCR processing failed: {e}")
        return "", 0.0, str(e)


def merge_text(original_text: str, ocr_text: str) -> Tuple[str, bool]:
    """
    Compare original extracted text with OCR'd text.
    Use OCR if it extracts strictly more than 20% additional text.

    Args:
        original_text: Text extracted by standard PDF/PPTX extraction (must be string, not None)
        ocr_text: Text extracted by OCR (must be string, not None)

    Returns:
        Tuple of (final_text, ocr_was_used)
        - final_text: The chosen text (either original or ocr, never modified)
        - ocr_was_used: Boolean indicating if OCR text was chosen

    Logic:
        - Compares character lengths after stripping whitespace
        - OCR is preferred only if len(ocr_text.strip()) > len(original_text.strip()) * 1.2
        - If both texts are empty, returns original_text and False
        - Returns the chosen text unchanged (no modification or concatenation)

    Example:
        original = "10 chars text"  # 10 chars (after strip)
        ocr = "This is much longer text from OCR"  # 33 chars (after strip)
        >>> merge_text(original, ocr)
        ('This is much longer text from OCR', True)  # 33 > 12, so OCR used
    """
    original_len = len(original_text.strip())
    ocr_len = len(ocr_text.strip())

    # 20% threshold: use OCR if it extracts significantly more
    threshold = original_len * 1.2

    if ocr_len > threshold:
        logger.debug(f"Using OCR text ({ocr_len} chars vs {original_len} original)")
        return ocr_text, True
    else:
        logger.debug(f"Keeping original text ({original_len} chars vs {ocr_len} OCR)")
        return original_text, False


def alert_ocr_failures(ocr_results: List[dict], lecture_title: str, webhook_url: Optional[str] = None) -> None:
    """Post Discord alert for OCR failures or low-confidence slides.

    Args:
        ocr_results: List of OCR result dicts from the pipeline.
        lecture_title: Title of the lecture for the alert header.
        webhook_url: Discord webhook URL. If None, reads DISCORD_HOOK_FEED from env.
    """
    failures = [r for r in ocr_results if r["status"] == "failed"]
    low_confidence = [
        r for r in ocr_results
        if r["status"] == "success" and r.get("confidence", 1.0) < 0.3
    ]

    if not failures and not low_confidence:
        return

    import os
    import json
    import urllib.request
    import urllib.error

    url = webhook_url or os.getenv("DISCORD_HOOK_FEED")
    if not url:
        logger.warning("No DISCORD_HOOK_FEED env var set; skipping OCR alert")
        return

    lines: List[str] = []
    for r in failures:
        lines.append(f"❌ Slide {r['slide']}: {r.get('error', 'unknown error')}")
    for r in low_confidence:
        lines.append(f"⚠️ Slide {r['slide']}: low confidence ({r['confidence']:.2f}) — verify manually")

    embed = {
        "title": f"OCR Alert: {lecture_title}",
        "description": "\n".join(lines),
        "color": 0xFF6B6B,
    }
    body = json.dumps({"embeds": [embed]}).encode()
    req = urllib.request.Request(
        f"{url}?wait=true",
        method="POST",
        data=body,
        headers={"Content-Type": "application/json", "User-Agent": "DiscordBot"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10):
            pass
    except (urllib.error.HTTPError, urllib.error.URLError, OSError) as exc:
        logger.error(f"Failed to post OCR alert: {exc}")


def format_ocr_summary(ocr_results: List[dict]) -> str:
    """
    Format OCR results into a summary line for the lecture note.

    Args:
        ocr_results: List of OCR result dicts, each with:
            - slide: slide number (int)
            - status: "success", "failed", or "skipped" (str)
            - ocr_used: boolean if OCR text was used (only if status=="success")
            - confidence: float 0-1 confidence score (only if status=="success")
            - error: error message string (only if status=="failed")

    Returns:
        Summary string like "OCR'd 2/3 slides; 2/3 successful; avg confidence 0.87"
    """
    total = len(ocr_results)
    successful = sum(1 for r in ocr_results if r["status"] == "success")
    ocr_used = sum(1 for r in ocr_results if r.get("ocr_used", False))

    confidences = [
        r["confidence"] for r in ocr_results
        if r["status"] == "success" and "confidence" in r
    ]
    avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0

    return f"OCR'd {ocr_used}/{total} slides; {successful}/{total} successful; avg confidence {avg_confidence:.2f}"
