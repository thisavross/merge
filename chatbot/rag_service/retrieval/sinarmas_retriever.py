"""
retrieval/sinarmas_retriever.py
────────────────────────────────
Company knowledge retrieval from the sinarmas_knowledge ChromaDB collection.

The collection is read-only at query time.
It is rebuilt by scripts/build_sinarmas_index.py whenever new PDFs are added to MinIO.
"""

from __future__ import annotations

from retrieval.chroma_store import _get_sinarmas_collection, chroma_search


def search_sinarmas(query_embedding: list[float], n: int = 3) -> list[str]:
    """Return the top-n sinarmas chunks most similar to query_embedding.

    Returns [] when the collection does not exist or is empty.
    This is intentional: the caller (chat_service) treats an empty result as
    "no company knowledge available" and proceeds without it.
    """
    col = _get_sinarmas_collection()
    if col is None or col.count() == 0:
        return []
    return chroma_search(col, query_embedding, n)  # type: ignore[return-value]