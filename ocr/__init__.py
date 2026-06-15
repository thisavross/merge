"""
local/ocr — document processing for Moda chatbot.

See FLOW.txt for architecture. Chatbot should import via integrations.ocr_client
when possible; direct imports are fine for batch scripts after bootstrap.
"""

from ocr.attachments import split_attachments
from ocr.course_files import extract_course_file_text
from ocr.text_extract import extract_text_from_bytes, is_probably_image, pdf_to_images_b64

__all__ = [
    "extract_course_file_text",
    "extract_text_from_bytes",
    "is_probably_image",
    "pdf_to_images_b64",
    "split_attachments",
]
