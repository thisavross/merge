"""Bridge local/ocr extract.py output into chatbot Chroma collections."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from bootstrap import ensure_local_packages

ensure_local_packages()

from config import Settings, settings
from infrastructure.ollama_client import get_embeddings
from retrieval.chroma_store import _get_chat_collection, _get_content_collection


def _stable_doc_id(path: Path, course_id: int | None, source_type: str) -> str:
    raw = f"{source_type}:{course_id or 0}:{path.name}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def _chunk_documents(result: dict[str, Any]) -> list[tuple[str, str]]:
    """Return (chunk_type, text) pairs from extract.py result."""
    out: list[tuple[str, str]] = []
    for chunk in result.get("chunks") or []:
        if not isinstance(chunk, dict):
            continue
        content = str(chunk.get("content") or "").strip()
        if not content:
            continue
        chunk_type = str(chunk.get("type") or "text").strip().lower() or "text"
        out.append((chunk_type, content))
    return out


def _upsert_batches(
    collection,
    *,
    ids: list[str],
    embeddings: list[list[float]],
    documents: list[str],
    metadatas: list[dict[str, Any]],
    batch_size: int = 100,
) -> None:
    for start in range(0, len(ids), batch_size):
        end = start + batch_size
        collection.add(
            ids=ids[start:end],
            embeddings=embeddings[start:end],
            documents=documents[start:end],
            metadatas=metadatas[start:end],
        )


def bridge_ingest_pdf(
    pdf_path: str | Path,
    *,
    course_id: int | None = None,
    source_type: str = "student_upload",
    st: Settings | None = None,
) -> dict[str, Any]:
    """
    Run extract.py on one PDF and store vectors in moodle_chat + moodle_course.

    Used by index_service.ingest_uploaded_pdf() and POST /admin/ingest/pdf.
    """
    st = st or settings
    path = Path(pdf_path)
    if not path.is_file():
        raise FileNotFoundError(str(path))

    from ocr.extract import process_file

    result = process_file(str(path))
    chunk_pairs = _chunk_documents(result)
    if not chunk_pairs:
        return {
            "doc_id": None,
            "chunk_count": 0,
            "table_count": 0,
            "status": "empty",
            "path": str(path),
        }

    doc_id = str(result.get("doc_id") or _stable_doc_id(path, course_id, source_type))
    cid = int(course_id or 0)
    source_name = path.name

    documents = [text for _, text in chunk_pairs]
    embeddings = get_embeddings(st, documents)

    chat_col = _get_chat_collection(st)
    content_col = _get_content_collection(st)

    chat_ids = [f"ocr_chat_{doc_id}_{i:04d}" for i in range(len(documents))]
    chat_metas = [
        {
            "course_id": cid,
            "source": source_name,
            "chunk_type": "general",
            "doc_id": doc_id,
            "source_type": source_type,
            "ocr_chunk_type": chunk_type,
        }
        for chunk_type, _ in chunk_pairs
    ]
    _upsert_batches(
        chat_col,
        ids=chat_ids,
        embeddings=embeddings,
        documents=documents,
        metadatas=chat_metas,
    )

    learning_pairs = [
        (chunk_type, text)
        for chunk_type, text in chunk_pairs
        if chunk_type in {"text", "table", "figure", "scanned_ocr"}
    ]
    if learning_pairs:
        learning_docs = [text for _, text in learning_pairs]
        learning_embeddings = get_embeddings(st, learning_docs)
        content_ids = [f"ocr_content_{doc_id}_{i:04d}" for i in range(len(learning_docs))]
        content_metas = [
            {
                "course_id": cid,
                "source": source_name,
                "chunk_type": "learning",
                "doc_id": doc_id,
                "source_type": source_type,
                "ocr_chunk_type": chunk_type,
            }
            for chunk_type, _ in learning_pairs
        ]
        _upsert_batches(
            content_col,
            ids=content_ids,
            embeddings=learning_embeddings,
            documents=learning_docs,
            metadatas=content_metas,
        )

    table_count = sum(1 for chunk_type, _ in chunk_pairs if chunk_type == "table")
    return {
        "doc_id": doc_id,
        "chunk_count": len(chunk_pairs),
        "table_count": table_count,
        "status": "ok",
        "path": str(path),
    }
