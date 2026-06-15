"""Process user-uploaded attachments into text blocks and vision image payloads."""

from __future__ import annotations

import base64
from pathlib import Path

from ocr.text_extract import extract_text_from_bytes, is_probably_image, pdf_to_images_b64


def split_attachments(
    attachments: list[dict] | None,
    *,
    pdf_vision_max_pages: int = 2,
    max_text_chars: int = 12000,
) -> tuple[str, list[str]]:
    """
    Build appended text block and list of raw base64 strings for vision models.

    attachments: list of {name, mime, data_base64}
    """
    if not attachments:
        return "", []

    text_parts: list[str] = []
    images_b64: list[str] = []

    for item in attachments:
        name = str(item.get("name") or "file")
        mime = str(item.get("mime") or "")
        b64 = str(item.get("data_base64") or "")
        if not b64:
            continue
        try:
            raw = base64.b64decode(b64, validate=False)
        except Exception:
            continue

        if is_probably_image(name, mime):
            images_b64.append(b64)
            continue

        extracted = extract_text_from_bytes(name, raw, mime)
        if extracted and extracted.strip():
            text_parts.append(f"--- {name} ---\n{extracted.strip()}")
        elif Path(name).suffix.lower() == ".pdf":
            pdf_images = pdf_to_images_b64(raw, max_pages=pdf_vision_max_pages)
            if pdf_images:
                images_b64.extend(pdf_images)
                text_parts.append(
                    f"--- {name} ---\n[PDF text empty; sent {len(pdf_images)} page image(s) for vision OCR.]"
                )

    block = "\n\n".join(text_parts).strip()
    if len(block) > max_text_chars:
        block = block[:max_text_chars] + "\n\n[…truncated…]"

    return block, images_b64
