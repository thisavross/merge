"""Pure text chunking utilities (no I/O)."""

from __future__ import annotations

import re


def _normalize_text_for_chunking(text: str) -> str:
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def chunk_text_bounded(text: str, chunk_size: int, max_chunks: int) -> list[str]:
    """Legacy chunking without overlap (used where overlap is not required)."""
    return chunk_text_with_overlap(text, chunk_size, overlap=0, max_chunks=max_chunks)


def chunk_text_with_overlap(
    text: str,
    chunk_size: int,
    overlap: int = 100,
    max_chunks: int = 40,
) -> list[str]:
    """
    Split text into overlapping chunks for embedding.

    overlap preserves context across chunk boundaries (important for quiz coherence).
    """
    text = _normalize_text_for_chunking(text)
    if not text:
        return []

    overlap = max(0, min(overlap, chunk_size - 1))
    step = max(1, chunk_size - overlap) if overlap else max(100, int(chunk_size * 0.75))

    chunks: list[str] = []
    pos = 0
    while pos < len(text) and len(chunks) < max_chunks:
        chunk = text[pos : pos + chunk_size]
        if chunk.strip():
            chunks.append(chunk)
        pos += step

    return chunks
