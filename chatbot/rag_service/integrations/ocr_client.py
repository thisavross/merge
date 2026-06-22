"""
Facade for local/ocr — all document processing from the chatbot goes through here.

Keeps import paths stable and gives one place to log or swap OCR implementations.
"""

from __future__ import annotations

import base64
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from bootstrap import ensure_local_packages

ensure_local_packages()

from ocr.attachments import split_attachments
from ocr.course_files import extract_course_file_text
from ocr.text_extract import extract_text_from_bytes, pdf_to_images_b64

if TYPE_CHECKING:
    from config import Settings

VisionOcrFn = Callable[[str, list[str]], str]


def run_extract_pipeline(
    file_path: str | Path,
    *,
    batch_size: int = 3,
) -> dict[str, Any]:
    """Run local/ocr/extract.py (Docling + YOLO + QwenVL) on a file path."""
    from ocr.extract import process_file

    return process_file(str(file_path), batch_size=batch_size)


def chunks_to_plaintext(
    result: dict[str, Any],
    *,
    max_chars: int = 12000,
) -> str:
    """Flatten extract.py chunk list into one prompt-friendly text block."""
    parts: list[str] = []
    for chunk in result.get("chunks") or []:
        if not isinstance(chunk, dict):
            continue
        content = str(chunk.get("content") or "").strip()
        if not content:
            continue
        page = chunk.get("page")
        section = str(chunk.get("section") or "").strip()
        chunk_type = str(chunk.get("type") or "text").strip()
        header_bits = [bit for bit in (f"page {page}" if page else "", section, chunk_type) if bit]
        header = " | ".join(header_bits) if header_bits else chunk_type
        parts.append(f"--- {header} ---\n{content}")

    block = "\n\n".join(parts).strip()
    if max_chars > 0 and len(block) > max_chars:
        block = block[:max_chars] + "\n\n[…truncated…]"
    return block


def extract_bytes_via_pipeline(
    filename: str,
    data: bytes,
    *,
    batch_size: int = 3,
    max_chars: int = 12000,
) -> str:
    """Write bytes to a temp file, run extract.py, return flattened plaintext."""
    suffix = Path(filename).suffix or ".bin"
    tmp_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(data)
            tmp_path = tmp.name
        result = run_extract_pipeline(tmp_path, batch_size=batch_size)
        return chunks_to_plaintext(result, max_chars=max_chars)
    finally:
        if tmp_path:
            Path(tmp_path).unlink(missing_ok=True)


def extract_file_via_pipeline(
    file_path: str | Path,
    *,
    batch_size: int = 3,
    max_chars: int = 12000,
) -> str:
    """Run extract.py on an on-disk file and return flattened plaintext."""
    result = run_extract_pipeline(file_path, batch_size=batch_size)
    return chunks_to_plaintext(result, max_chars=max_chars)


def extract_document_bytes(filename: str, data: bytes, mime: str = "") -> str:
    """Extract text from raw file bytes (PDF, Office, text, …)."""
    return extract_text_from_bytes(filename, data, mime)


def split_user_attachments(
    attachments: list[dict] | None,
    *,
    pdf_vision_max_pages: int = 2,
    max_text_chars: int = 12000,
    use_extract_pipeline: bool = False,
) -> tuple[str, list[str]]:
    """User uploads in /chat → prompt text block + vision image payloads."""
    if not use_extract_pipeline:
        return split_attachments(
            attachments,
            pdf_vision_max_pages=pdf_vision_max_pages,
            max_text_chars=max_text_chars,
        )

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

        ext = Path(name).suffix.lower()
        if ext in {".pdf", ".docx", ".pptx", ".xlsx", ".xlsm", ".csv", ".html", ".md", ".txt"}:
            try:
                extracted = extract_bytes_via_pipeline(
                    name,
                    raw,
                    max_chars=max_text_chars,
                )
                if extracted.strip():
                    text_parts.append(f"--- {name} ---\n{extracted.strip()}")
                    continue
            except Exception as exc:
                text_parts.append(f"--- {name} ---\n[Pipeline extract failed: {exc}]")

        block, imgs = split_attachments(
            [item],
            pdf_vision_max_pages=pdf_vision_max_pages,
            max_text_chars=max_text_chars,
        )
        if block:
            text_parts.append(block)
        images_b64.extend(imgs)

    block = "\n\n".join(text_parts).strip()
    if len(block) > max_text_chars:
        block = block[:max_text_chars] + "\n\n[…truncated…]"
    return block, images_b64


def build_vision_ocr_fn(settings: Settings) -> VisionOcrFn:
    """Ollama vision OCR for scanned PDFs during course indexing."""
    from infrastructure.ollama_client import chat_completion
    from text_format import prettify_reply

    vision_model = (getattr(settings, "ollama_vision_model", "") or "").strip() or getattr(
        settings, "ollama_chat_model", ""
    )
    system = (
        "You are a Vision engine. Extract all readable text from the provided image(s). "
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
    *,
    use_extract_pipeline: bool = False,
) -> str:
    """Course file from dataroot → plain text (native extract + vision OCR fallback)."""
    if use_extract_pipeline:
        try:
            extracted = extract_bytes_via_pipeline(filename, data)
            if extracted.strip():
                return extracted.strip()
        except Exception:
            pass

    ocr_pages = int(getattr(settings, "course_pdf_ocr_max_pages", 2) or 2)
    return extract_course_file_text(
        filename,
        data,
        mimetype,
        pdf_ocr_max_pages=ocr_pages,
        vision_ocr=build_vision_ocr_fn(settings),
    )


def ingest_pdf_to_index(
    pdf_path: str | Path,
    *,
    course_id: int | None = None,
    source_type: str = "student_upload",
) -> dict[str, Any]:
    """Run extract.py pipeline and store vectors via ocr_ingest_bridge."""
    from integrations.ocr_ingest_bridge import bridge_ingest_pdf

    return bridge_ingest_pdf(
        pdf_path,
        course_id=course_id,
        source_type=source_type,
    )
