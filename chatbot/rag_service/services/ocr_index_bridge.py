"""
integrations/ocr_ingest_bridge.py
───────────────────────────────────
Bridge between the OCR module (extract.process_pdf) and the chatbot's
ChromaDB ingestion pipeline (retrieval.chroma_store.ingest_pdf).

Responsibilities
─────────────────
1. Load and hold the bge-m3 sentence-transformers model as a module-level
   singleton — one load per process, shared across all ingest calls.
2. Expose a single public function, bridge_ingest_pdf(), that index_service
   can call without knowing anything about sentence-transformers or the OCR layer.
3. Keep the dependency on sentence-transformers and the OCR extract module
   isolated here so chroma_store.py stays import-clean.

Dependency graph
─────────────────
  index_service  ──►  ocr_ingest_bridge  ──►  retrieval.chroma_store.ingest_pdf
                                          ──►  extract.process_pdf  (OCR module)
                                          ──►  sentence_transformers.SentenceTransformer
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

# ── Model singleton ───────────────────────────────────────────────────────────
# Loaded lazily on first call so importing this module at startup does not
# block the FastAPI worker while the model downloads / loads from disk.

_model: SentenceTransformer | None = None
_model_lock = threading.Lock()

# Override via env var EMBED_MODEL_NAME; defaults to bge-m3.
import os
_EMBED_MODEL_NAME = os.getenv("EMBED_MODEL_NAME", "BAAI/bge-m3")


def _get_model() -> "SentenceTransformer":
    """Return the singleton embedding model, loading it on the first call."""
    global _model
    if _model is not None:
        return _model
    with _model_lock:
        if _model is not None:  # double-checked inside lock
            return _model
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise RuntimeError(
                "sentence-transformers is not installed. "
                "Run: pip install sentence-transformers"
            ) from exc
        print(f"[ocr_ingest_bridge] Loading embedding model: {_EMBED_MODEL_NAME}")
        _model = SentenceTransformer(_EMBED_MODEL_NAME)
        print(f"[ocr_ingest_bridge] Model loaded: {_EMBED_MODEL_NAME}")
    return _model


def _get_process_pdf():
    """Return process_pdf callable from the OCR extract module.

    Imported lazily so the OCR module (and its heavy deps: torch, docling,
    YOLO) are not loaded unless PDF ingestion is actually triggered.
    """
    try:
        from extract import process_pdf  # OCR module; must be on sys.path
    except ImportError as exc:
        raise RuntimeError(
            "OCR extract module not found. "
            "Ensure the ocr/ package is on PYTHONPATH."
        ) from exc
    return process_pdf


# ── Public entry point ────────────────────────────────────────────────────────

def bridge_ingest_pdf(
    pdf_path: str | Path,
    *,
    course_id: int | None = None,
    source_type: str = "student_upload",
) -> dict:
    """Index a PDF file into ChromaDB via the OCR pipeline.

    Parameters
    ----------
    pdf_path:
        Absolute or relative path to the PDF file on disk.
    course_id:
        Moodle course_id to associate with the document. Pass None (or omit)
        for uploads that are not tied to a specific course (e.g. Sinarmas PDFs
        ingested outside the normal Sinarmas rebuild flow).
    source_type:
        Label stored in Chroma metadata. Callers should use one of:
          - "student_upload"  — file uploaded by a student/teacher via the API
          - "sinarmas"        — company knowledge PDF (alternative to full rebuild)
        Custom values are allowed and will be queryable via retrieve_pdf_chunks().

    Returns
    -------
    dict with keys:
        doc_id       (str)  — stable MD5 ID stored in document_index
        chunk_count  (int)  — number of chunks written to rag_chunks
        table_count  (int)  — number of table chunks detected
        status       (str)  — "ok" | "empty" | "empty_repr" | "no_chunks"

    Raises
    ------
    RuntimeError   if sentence-transformers or the OCR extract module is missing.
    FileNotFoundError if the PDF path does not exist.
    """
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    # Lazy-load heavy deps only when actually needed.
    model = _get_model()
    process_pdf = _get_process_pdf()

    # Delegate to the unified ingest function in chroma_store.
    from retrieval.chroma_store import ingest_pdf  # local import avoids circular deps
    return ingest_pdf(
        pdf_path,
        model,
        process_pdf,
        course_id=course_id,
        source_type=source_type,
    )


def unload_model() -> None:
    """Release the model from memory (useful in tests or after a batch ingest).

    The next call to bridge_ingest_pdf() will reload the model from disk.
    """
    global _model
    with _model_lock:
        _model = None
    print("[ocr_ingest_bridge] Embedding model unloaded.")