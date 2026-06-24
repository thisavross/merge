"""
retrieval/sinarmas_retriever.py
────────────────────────────────
Company knowledge retrieval from the sinarmas_knowledge ChromaDB collection.

The collection is read-only at query time.
It is rebuilt by scripts/build_sinarmas_index.py whenever new PDFs are added to MinIO.
"""

from __future__ import annotations

from retrieval.chroma_store import _get_sinarmas_collection, chroma_search, chroma_search_adaptive


def search_sinarmas(
    query_embedding: list[float],
    n: int = 3,
    *,
    adaptive: bool = True,
    adaptive_multiplier: int = 3,
    adaptive_min_gap: float = 0.05,
) -> list[str]:
    """Return the top-n sinarmas chunks most similar to query_embedding.

    When adaptive=True (default), fetches up to n*adaptive_multiplier candidates
    and applies adaptive-k cutoff at the largest similarity gap.

    Returns [] when the collection does not exist or is empty.
    This is intentional: the caller (chat_service) treats an empty result as
    "no company knowledge available" and proceeds without it.
    """
    col = _get_sinarmas_collection()
    if col is None or col.count() == 0:
        return []
    if adaptive:
        return chroma_search_adaptive(
            col,
            query_embedding,
            max_k=n * adaptive_multiplier,
            min_k=1,
            min_gap=adaptive_min_gap,
        )
    return chroma_search(col, query_embedding, n)  # type: ignore[return-value]