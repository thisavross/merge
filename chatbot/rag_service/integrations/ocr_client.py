"""
Facade for local/ocr — all document processing from the chatbot goes through here.

Keeps import paths stable and gives one place to log or swap OCR implementations.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from bootstrap import ensure_local_packages

ensure_local_packages()

from ocr.attachments import split_attachments
from ocr.course_files import extract_course_file_text
from ocr.text_extract import extract_text_from_bytes, pdf_to_images_b64

if TYPE_CHECKING:
    from config import Settings

VisionOcrFn = Callable[[str, list[str]], str]


def extract_document_bytes(filename: str, data: bytes, mime: str = "") -> str:
    """Extract text from raw file bytes (PDF, Office, text, …)."""
    return extract_text_from_bytes(filename, data, mime)


def split_user_attachments(
    attachments: list[dict] | None,
    *,
    pdf_vision_max_pages: int = 2,
    max_text_chars: int = 12000,
) -> tuple[str, list[str]]:
    """User uploads in /chat → prompt text block + vision image payloads."""
    return split_attachments(
        attachments,
        pdf_vision_max_pages=pdf_vision_max_pages,
        max_text_chars=max_text_chars,
    )


def build_vision_ocr_fn(settings: Settings) -> VisionOcrFn:
    """Ollama vision OCR for scanned PDFs during course indexing."""
    from infrastructure.ollama_client import chat_completion
    from text_format import prettify_reply

    vision_model = (getattr(settings, "ollama_vision_model", "") or "").strip() or getattr(
        settings, "ollama_chat_model", ""
    )
    system = (
        "You are an OCR engine. Extract all readable text from the provided image(s). "
        "Return only the extracted text, as plain text, preserving line breaks when possible."
    )

    def vision_ocr(filename: str, images_b64: list[str]) -> str:
        user_message = f"Please OCR the following PDF page image(s) for file: {filename}."
        ocr_result = chat_completion(
            settings,
            system,
            user_message,
            images=images_b64,
            model=vision_model,
        )
        return prettify_reply(ocr_result.text)

    return vision_ocr


def extract_moodle_course_file(
    settings: Settings,
    filename: str,
    data: bytes,
    mimetype: str = "",
) -> str:
    """Course file from dataroot → plain text (native extract + vision OCR fallback)."""
    ocr_pages = int(getattr(settings, "course_pdf_ocr_max_pages", 2) or 2)
    return extract_course_file_text(
        filename,
        data,
        mimetype,
        pdf_ocr_max_pages=ocr_pages,
        vision_ocr=build_vision_ocr_fn(settings),
    )
