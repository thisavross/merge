"""Extract text from Moodle course files (native parse + optional vision OCR)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from ocr.text_extract import extract_text_from_bytes, pdf_to_images_b64

VisionOcrFn = Callable[[str, list[str]], str]


def extract_course_file_text(
    filename: str,
    data: bytes,
    mimetype: str = "",
    *,
    pdf_ocr_max_pages: int = 2,
    vision_ocr: VisionOcrFn | None = None,
) -> str:
    """
      Best-effort plain text for a course-attached file.

      If native PDF text is empty (scanned PDFs), renders pages and calls vision_ocr
    when provided.
    """
    extracted = ""
    try:
        extracted = extract_text_from_bytes(filename, data, mimetype) or ""
    except Exception:
        extracted = ""

    if extracted.strip():
        return extracted.strip()

    if Path(filename).suffix.lower() != ".pdf":
        return ""

    images_b64 = pdf_to_images_b64(data, max_pages=pdf_ocr_max_pages)
    if not images_b64 or vision_ocr is None:
        return ""

    try:
        return (vision_ocr(filename, images_b64) or "").strip()
    except Exception:
        return ""
