"""Course and Sinarmas index maintenance."""

# from __future__ import annotations

# from config import settings
# from retrieval.chroma_store import (
#     ensure_course_indexed,
#     reset_chroma_client,
#     schedule_course_reindex,
# )
# from infrastructure.redis_store import clear_summary_cache


# def run_sinarmas_rebuild() -> None:
#     """Rebuild Sinarmas Chroma collection and reset the shared client."""
#     from scripts import build_sinarmas_index

#     build_sinarmas_index.build()
#     reset_chroma_client()


# def warm_course_index(course_id: int, *, sync: bool = True) -> str:
#     """Index one Moodle course (blocking when sync=True)."""
#     col, name = ensure_course_indexed(
#         int(course_id),
#         settings,
#         force_sync=sync,
#     )
#     clear_summary_cache(int(course_id))  

#     _ = col
#     return name


# def queue_course_reindex(course_id: int) -> bool:
#     """Schedule background re-index for one course."""
#     return schedule_course_reindex(int(course_id), settings)

 
from __future__ import annotations
 
from pathlib import Path
 
from config import settings
from retrieval.chroma_store import (
    ensure_course_indexed,
    reset_chroma_client,
    schedule_course_reindex,
)
from infrastructure.redis_store import clear_summary_cache
 
 
# ── Moodle course index ───────────────────────────────────────────────────────
 
def warm_course_index(course_id: int, *, sync: bool = True) -> str:
    """Index one Moodle course, blocking until complete when sync=True."""
    col, name = ensure_course_indexed(
        int(course_id),
        settings,
        force_sync=sync,
    )
    clear_summary_cache(int(course_id))
    _ = col
    return name
 
 
def queue_course_reindex(course_id: int) -> bool:
    """Schedule background re-index for one Moodle course."""
    return schedule_course_reindex(int(course_id), settings)
 
 
# ── Sinarmas knowledge index ──────────────────────────────────────────────────
 
def run_sinarmas_rebuild() -> None:
    """Rebuild the sinarmas_knowledge Chroma collection and reset the client.
 
    This is a full rebuild — it re-reads every PDF from MinIO and replaces
    all existing vectors. Use ingest_uploaded_pdf(source_type="sinarmas")
    for lightweight on-demand ingestion of a single new PDF.
    """
    from scripts import build_sinarmas_index
    build_sinarmas_index.build()
    reset_chroma_client()
 
 
# ── PDF upload index ──────────────────────────────────────────────────────────
 
def ingest_uploaded_pdf(
    pdf_path: str | Path,
    *,
    course_id: int | None = None,
    source_type: str = "student_upload",
) -> dict:
    """Index a single PDF into document_index + rag_chunks via the OCR pipeline.
 
    This is the main entry point for the POST /ingest-pdf API route.
 
    Parameters
    ----------
    pdf_path:
        Absolute path to the PDF on disk (already saved by the upload handler).
    course_id:
        Moodle course_id to associate with this document.
        Pass None for PDFs not tied to a specific course.
    source_type:
        "student_upload" for files uploaded by users.
        "sinarmas" for company knowledge PDFs added outside the full rebuild.
 
    Returns
    -------
    dict with keys: doc_id, chunk_count, table_count, status.
 
    Raises
    ------
    FileNotFoundError   if pdf_path does not exist.
    RuntimeError        if sentence-transformers or the OCR module is missing.
    """
    from integrations.ocr_ingest_bridge import bridge_ingest_pdf
    return bridge_ingest_pdf(
        pdf_path,
        course_id=course_id,
        source_type=source_type,
    )
 
 
def ingest_uploaded_pdfs_batch(
    pdf_paths: list[str | Path],
    *,
    course_id: int | None = None,
    source_type: str = "student_upload",
    stop_on_error: bool = False,
) -> list[dict]:
    """Index multiple PDFs sequentially, sharing one model load.
 
    The embedding model is loaded once by the first call to bridge_ingest_pdf
    and reused for all subsequent PDFs in the batch (module-level singleton in
    ocr_ingest_bridge).
 
    Parameters
    ----------
    pdf_paths:
        List of paths to process in order.
    course_id:
        Applied to all PDFs in the batch. For mixed-course batches, call
        ingest_uploaded_pdf() per file instead.
    source_type:
        Applied uniformly to all PDFs in the batch.
    stop_on_error:
        When True, re-raise the first exception and abort the batch.
        When False (default), log the error and continue with remaining files.
 
    Returns
    -------
    List of result dicts in the same order as pdf_paths.
    Failed items have status="error" and an "error" key with the message.
    """
    from integrations.ocr_ingest_bridge import bridge_ingest_pdf
 
    results: list[dict] = []
    for path in pdf_paths:
        try:
            result = bridge_ingest_pdf(
                path,
                course_id=course_id,
                source_type=source_type,
            )
            results.append(result)
        except Exception as exc:
            error_result = {
                "doc_id": None,
                "chunk_count": 0,
                "table_count": 0,
                "status": "error",
                "error": str(exc),
                "path": str(path),
            }
            results.append(error_result)
            print(f"[index_service] Batch ingest error for {path}: {exc}")
            if stop_on_error:
                raise
    return results