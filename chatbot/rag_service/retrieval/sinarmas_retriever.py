"""
retrieval/sinarmas_retriever.py
────────────────────────────────
Company knowledge retrieval from the sinarmas_knowledge ChromaDB collection.

The collection is read-only at query time.
It is rebuilt by scripts/build_sinarmas_index.py whenever new PDFs are added to MinIO.
"""

# from __future__ import annotations

# from retrieval.chroma_store import _get_sinarmas_collection, chroma_search


# def search_sinarmas(query_embedding: list[float], n: int = 3) -> list[str]:
#     """Return the top-n sinarmas chunks most similar to query_embedding.

#     Returns [] when the collection does not exist or is empty.
#     This is intentional: the caller (chat_service) treats an empty result as
#     "no company knowledge available" and proceeds without it.
#     """
#     col = _get_sinarmas_collection()
#     if col is None or col.count() == 0:
#         return []
#     return chroma_search(col, query_embedding, n)  # type: ignore[return-value]

 
from __future__ import annotations
 
from retrieval.chroma_store import (
    _get_sinarmas_collection,
    chroma_search,
    retrieve_pdf_chunks,
)
 
# Minimum similarity score to include a rag_chunks result.
# Prevents low-quality matches from contaminating answers when the main
# sinarmas_knowledge collection already has good coverage.
_RAG_MIN_SCORE = 0.45
 
# How many chunks to pull from rag_chunks when used as a fallback or supplement.
_RAG_FALLBACK_N = 5
 
 
def search_sinarmas(
    query_embedding: list[float],
    n: int = 3,
    *,
    course_id: int | None = None,
    supplement_with_uploads: bool = True,
) -> list[str]:
    """Return the top-n sinarmas chunks most similar to query_embedding.
 
    Parameters
    ----------
    query_embedding:
        Pre-computed query vector (same model used at index time).
    n:
        Number of chunks to return from the primary sinarmas_knowledge
        collection.
    course_id:
        When set, also filters rag_chunks by this course_id so that only
        PDFs uploaded for this specific course are included.
    supplement_with_uploads:
        When True (default), always merge results from rag_chunks indexed
        with source_type="sinarmas" — useful when the main collection
        exists but a recently uploaded PDF hasn't been added to it yet.
        Set to False to query only the curated sinarmas_knowledge collection.
 
    Returns
    -------
    Deduplicated list of chunk texts, primary collection results first.
    Returns [] when neither source has relevant content.
 
    Notes
    -----
    An empty result is intentional: chat_service treats [] as "no company
    knowledge available" and continues without a Sinarmas context block.
    """
    results: list[str] = []
 
    # ── Path 1: curated sinarmas_knowledge collection ─────────────────────────
    col = _get_sinarmas_collection()
    if col is not None and col.count() > 0:
        results = chroma_search(col, query_embedding, n)  # type: ignore[assignment]
 
    # ── Path 2: rag_chunks with source_type="sinarmas" ────────────────────────
    # Always run when supplement_with_uploads=True so recently uploaded PDFs
    # (not yet in the curated collection) are also surfaced.
    if supplement_with_uploads:
        raw: list[tuple[float, str]] = retrieve_pdf_chunks(  # type: ignore[assignment]
            query_embedding,
            top_k=_RAG_FALLBACK_N,
            source_type="sinarmas",
            course_id=course_id,
            include_scores=True,
        )
        for score, chunk in raw:
            # Skip low-confidence matches and chunks already in results.
            sig = (chunk or "")[:200].lower().strip()
            already_have = any(
                (r or "")[:200].lower().strip() == sig for r in results
            )
            if score >= _RAG_MIN_SCORE and not already_have:
                results.append(chunk)
 
    return results