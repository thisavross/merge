"""
retrieval/chroma_store.py
─────────────────────────
ChromaDB client, collection access, indexing, and vector search.

THREE COLLECTIONS ONLY (names from config/.env):
  moodle_chat        — broad general chunks for everyday chat (chunk_type="general")
  moodle_course      — learning-only chunks for quiz / summarize (chunk_type="learning")
  sinarmas_knowledge — company PDF knowledge, built by scripts/build_sinarmas_index.py

ALL Moodle course vectors share moodle_chat + moodle_course, scoped by metadata course_id.

Legacy names (moodle_quiz, moodle_coursecontent, course_*) are not used.
Run scripts/rename_to_moodle_course.py once if upgrading an old chroma_db/.

Dependency rule: this module imports only from
  config, domain.chunking, retrieval.content_filter,
  infrastructure.moodle_db, infrastructure.ollama_client
"""

from __future__ import annotations

import math
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import TYPE_CHECKING

import chromadb

from config import Settings, settings
from domain.chunking import chunk_text_with_overlap
from infrastructure.moodle_db import (
    get_course_meta,
    list_enrolled_course_ids,
    load_course_plaintext,
)
from infrastructure.ollama_client import get_embeddings
from infrastructure.redis_store import get_course_meta as redis_get_course_meta
from infrastructure.redis_store import set_course_meta as redis_set_course_meta
from retrieval.content_filter import (
    is_assignment_or_instruction_chunk,
    is_substantive_learning_content,
)

if TYPE_CHECKING:
    pass

# ── ChromaDB path ─────────────────────────────────────────────────────────────
_CHROMA_PATH = Path(__file__).resolve().parents[1] / "chroma_db"

# ── Singleton client (one per process) ───────────────────────────────────────
_chroma_client: chromadb.HttpClient | None = None

# ── In-process course freshness cache: {course_id: timemodified} ─────────────
# Avoids hitting MySQL on every request just to check whether the course changed.
# A process restart clears this cache — safe, just triggers one re-check per course.
_course_tm_cache: dict[int, int] = {}
_course_name_cache: dict[int, str] = {}

# Background indexing (avoid blocking /chat on full re-index).
_index_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="course-index")
_indexing_lock = threading.Lock()
_indexing_courses: set[int] = set()

# Legacy import path for tests/docs.
CACHE_SIMILARITY_THRESHOLD = 0.92


def semantic_cache_threshold(st: Settings | None = None) -> float:
    st = st or settings
    return float(getattr(st, "semantic_cache_threshold", CACHE_SIMILARITY_THRESHOLD) or CACHE_SIMILARITY_THRESHOLD)


def is_course_indexing(course_id: int) -> bool:
    with _indexing_lock:
        return int(course_id) in _indexing_courses


def schedule_course_reindex(course_id: int, st: Settings | None = None) -> bool:
    """Queue a full re-index unless one is already running. Returns True if scheduled."""
    cid = int(course_id)
    st = st or settings
    with _indexing_lock:
        if cid in _indexing_courses:
            return False
        _indexing_courses.add(cid)

    def _run() -> None:
        try:
            _index_course(cid, st)
        except Exception as e:
            print(f"[Index] Background failed course_id={cid}: {e}")
        finally:
            with _indexing_lock:
                _indexing_courses.discard(cid)

    _index_executor.submit(_run)
    print(f"[Index] Scheduled background re-index for course_id={cid}")
    return True


def _resolve_course_meta(st: Settings, course_id: int) -> tuple[str, int]:
    """Course name + timemodified from in-process, Redis, then MySQL."""
    cached_tm = _course_tm_cache.get(course_id)
    cached_name = _course_name_cache.get(course_id)
    if cached_tm is not None and cached_name:
        return cached_name, cached_tm

    redis_meta = redis_get_course_meta(course_id)
    if redis_meta:
        name = str(redis_meta.get("fullname") or "").strip() or f"Course {course_id}"
        tm = int(redis_meta.get("timemodified") or 0)
        _course_name_cache[course_id] = name
        _course_tm_cache[course_id] = tm
        return name, tm

    name, tm = get_course_meta(st, course_id)
    if name:
        _course_name_cache[course_id] = name
        _course_tm_cache[course_id] = tm
        redis_set_course_meta(course_id, name, tm)
    return name or f"Course {course_id}", tm


# ─────────────────────────────────────────────────────────────────────────────
# Client management
# ─────────────────────────────────────────────────────────────────────────────
def _get_client():
    global _chroma_client

    if _chroma_client is None:
        _chroma_client = chromadb.HttpClient(
            host=settings.chroma_host,
            port=settings.chroma_port,
        )

    return _chroma_client


def reset_chroma_client() -> None:
    """Force the singleton to be recreated on the next request.
    Call this after a Sinarmas index rebuild so stale file handles are released."""
    global _chroma_client
    _chroma_client = None


def _get_or_create_cosine_collection(name: str) -> chromadb.Collection:
    """Open or create a collection using cosine similarity (hnsw:space='cosine').

    Why cosine and not L2?
    bge-m3 / qwen3-embedding encode meaning as direction, not magnitude.
    Cosine ignores vector length, so a short sentence and a long paragraph
    about the same concept still score highly against each other.
    """
    return _get_client().get_or_create_collection(
        name=name,
        metadata={"hnsw:space": "cosine"},
    )


# ─────────────────────────────────────────────────────────────────────────────
# The three canonical collection accessors
# ─────────────────────────────────────────────────────────────────────────────

def _get_chat_collection(st: Settings | None = None) -> chromadb.Collection:
    """moodle_chat — broad context, used by general answer pipeline."""
    return _get_or_create_cosine_collection((st or settings).moodle_chat_collection)


def _get_content_collection(st: Settings | None = None) -> chromadb.Collection:
    """moodle_course — learning-only, used by quiz and summarize."""
    return _get_or_create_cosine_collection((st or settings).moodle_coursecontent_collection)


def _get_sinarmas_collection() -> chromadb.Collection | None:
    """sinarmas_knowledge — read-only at query time; written by build_sinarmas_index.py."""
    try:
        names = [c.name for c in _get_client().list_collections()]
        if "sinarmas_knowledge" not in names:
            print("[WARN] sinarmas_knowledge missing. Run: python scripts/build_sinarmas_index.py")
            return None
        return _get_client().get_collection("sinarmas_knowledge")
    except Exception as e:
        print(f"[ERROR] sinarmas_knowledge: {e}")
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Pure cosine similarity (no numpy)
# ─────────────────────────────────────────────────────────────────────────────

def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two equal-length float vectors.

    Used by the Redis semantic cache to decide whether to reuse a cached reply.
    Pure Python is fast enough for ≤200 cached entries per course.
    """
    if len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    mag_a = math.sqrt(sum(x * x for x in a))
    mag_b = math.sqrt(sum(x * x for x in b))
    if mag_a == 0.0 or mag_b == 0.0:
        return 0.0
    return dot / (mag_a * mag_b)


# ─────────────────────────────────────────────────────────────────────────────
# Generic search helper
# ─────────────────────────────────────────────────────────────────────────────

def _count_where(col: chromadb.Collection, course_id: int) -> int:
    """Count chunks for one course_id without loading documents."""
    try:
        result = col.get(where={"course_id": course_id}, include=[])
        return len(result.get("ids") or [])
    except Exception:
        return 0


def chroma_search(
    col: chromadb.Collection,
    query_embedding: list[float],
    n: int,
    *,
    where: dict | None = None,
    include_scores: bool = False,
) -> list[str] | list[tuple[float, str]]:
    """Vector search on any collection.

    ChromaDB cosine distance is in [0, 2]; we convert to similarity = 1 - distance.

    Returns:
      list[str]                   when include_scores=False (default)
      list[tuple[float, str]]     when include_scores=True  (similarity, chunk)
    """
    count = _count_where(col, int(where["course_id"])) if where else col.count()
    n = min(n, max(1, count))
    if n == 0:
        return []

    include_fields = ["documents", "distances"] if include_scores else ["documents"]
    results = col.query(
        query_embeddings=[query_embedding],
        n_results=n,
        where=where,
        include=include_fields,
    )
    docs = results.get("documents", [[]])[0] or []

    if not include_scores:
        return [d for d in docs if d]

    dists = results.get("distances", [[]])[0] or []
    return [
        (round(1.0 - float(d), 4), doc)
        for d, doc in zip(dists, docs)
        if doc
    ]


def _adaptive_k_cutoff(
    scored_hits: list[tuple[float, str]],
    *,
    min_k: int = 1,
    min_gap: float = 0.05,
) -> list[str]:
    """Apply Taguchi et al. adaptive-k: k = argmax(sᵢ - sᵢ₊₁).

    Finds the index of the largest drop in similarity scores and cuts there.
    Falls back to returning all hits when no gap exceeds min_gap.

    Args:
        scored_hits: list of (similarity, chunk) sorted descending by similarity.
        min_k:       minimum number of chunks to always keep.
        min_gap:     minimum gap size to be considered a meaningful drop.
    """
    if len(scored_hits) <= min_k:
        return [doc for _, doc in scored_hits]

    scores = [s for s, _ in scored_hits]
    gaps = [scores[i] - scores[i + 1] for i in range(len(scores) - 1)]

    max_gap = max(gaps)
    if max_gap < min_gap:
        # No significant gap — return all candidates
        return [doc for _, doc in scored_hits]

    # argmax gives the index BEFORE the big drop; cut_at is how many to keep
    cut_at = gaps.index(max_gap) + 1
    cut_at = max(cut_at, min_k)

    print(f"[AdaptiveK] gap={max_gap:.4f} at position {cut_at}/{len(scored_hits)} "
          f"scores={[round(s, 3) for s in scores]}")
    return [doc for _, doc in scored_hits[:cut_at]]


def chroma_search_adaptive(
    col: chromadb.Collection,
    query_embedding: list[float],
    max_k: int,
    *,
    where: dict | None = None,
    min_k: int = 1,
    min_gap: float = 0.05,
) -> list[str]:
    """Adaptive-k search based on Taguchi et al.

    Fetches up to max_k candidates with scores, then cuts at the index of the
    largest similarity gap (argmax sᵢ - sᵢ₊₁).  This avoids padding the prompt
    with low-relevance chunks that push useful content out of the context window.

    Falls back to all max_k chunks when no significant gap is found.
    """
    scored: list[tuple[float, str]] = chroma_search(  # type: ignore[assignment]
        col, query_embedding, max_k, where=where, include_scores=True
    )
    if not scored:
        return []
    return _adaptive_k_cutoff(scored, min_k=min_k, min_gap=min_gap)


# ─────────────────────────────────────────────────────────────────────────────
# Document loaders (fetch without re-embedding)
# ─────────────────────────────────────────────────────────────────────────────

def _get_course_documents(
    col: chromadb.Collection,
    course_id: int,
    *,
    include_embeddings: bool = False,
) -> list[tuple[str, list[float] | None]]:
    """Load all stored chunks for a course from a given collection.

    Returns list of (text, embedding_or_None) tuples.
    When include_embeddings=True the returned embeddings are used for
    local cosine re-ranking (avoids a second Chroma query for quiz ranking).
    """
    include_fields = ["documents"]
    if include_embeddings:
        include_fields.append("embeddings")
    try:
        result = col.get(where={"course_id": course_id}, include=include_fields)
    except Exception:
        return []

    docs = result.get("documents") or []
    embs = result.get("embeddings") if include_embeddings else None
    out: list[tuple[str, list[float] | None]] = []

    for i, doc in enumerate(docs):
        if not doc or not str(doc).strip():
            continue
        emb: list[float] | None = None
        if embs is not None and i < len(embs) and embs[i] is not None:
            emb = list(embs[i])
        out.append((str(doc), emb))
    return out


def get_content_documents(
    course_id: int,
    st: Settings | None = None,
    *,
    include_embeddings: bool = False,
) -> list[tuple[str, list[float] | None]]:
    """Load learning-only chunks from moodle_course for a course."""
    return _get_course_documents(
        _get_content_collection(st),
        course_id,
        include_embeddings=include_embeddings,
    )


def get_learning_chunks_for_summary(
    course_id: int,
    st: Settings | None = None,
) -> list[str]:
    """Return all learning chunks for a course, filtered to chunk_type='learning'.

    Summary retrieval fetches ALL chunks (not top-K) so the LLM sees the full
    course material, not just the chunks most similar to 'summarize course'.
    """
    col = _get_content_collection(st)
    result = col.get(
        where={"course_id": course_id},
        include=["documents", "metadatas"],
    )
    docs: list[str] = []
    for doc, meta in zip(
        result.get("documents") or [],
        result.get("metadatas") or [],
    ):
        if not doc:
            continue
        if meta and meta.get("chunk_type") != "learning":
            continue
        text = str(doc).strip()
        if len(text.split()) >= 20:
            docs.append(text)
    return docs


# ─────────────────────────────────────────────────────────────────────────────
# Deduplication
# ─────────────────────────────────────────────────────────────────────────────

def dedupe_chunks(chunks: list[str], max_chunks: int) -> list[str]:
    """Drop near-duplicate chunks before LLM prompt assembly.

    Uses the first 200 characters (lowercased) as a similarity fingerprint.
    This catches the most common duplicates (re-indexed chunks with minor whitespace
    differences) without expensive pairwise comparison.
    """
    seen: set[str] = set()
    out: list[str] = []
    for chunk in chunks:
        sig = (chunk or "")[:200].lower().strip()
        if not sig or sig in seen:
            continue
        seen.add(sig)
        out.append(chunk)
        if len(out) >= max_chunks:
            break
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Quiz-specific re-ranking
# ─────────────────────────────────────────────────────────────────────────────

def rank_chunks_for_quiz(
    chunks: list[tuple[str, list[float] | None]],
    query_vec: list[float],
    max_chunks: int,
) -> list[str]:
    """Re-rank content chunks for quiz generation.

    Scoring:
      - Assignment/instruction chunks are excluded (they produce meta-questions
        like "what is the purpose of this lab?" instead of testing concepts).
      - Chunks are ranked by cosine similarity to the query embedding when
        embeddings are available.
      - If no embedding is stored (older index), chunk length is used as a
        proxy for information density.
    """
    usable: list[tuple[float, str]] = []
    for doc, emb in chunks:
        if is_assignment_or_instruction_chunk(doc):
            continue
        if not is_substantive_learning_content(doc):
            continue
        score = (
            cosine_similarity(query_vec, emb)
            if emb
            else min(1.0, len(doc) / 2000.0)
        )
        usable.append((score, doc))

    if not usable:
        return []

    usable.sort(key=lambda t: t[0], reverse=True)
    return dedupe_chunks([d for _, d in usable], max_chunks)


# ─────────────────────────────────────────────────────────────────────────────
# Course indexing
# ─────────────────────────────────────────────────────────────────────────────

def _coursename_from_plaintext(plain: str, course_id: int) -> str:
    for line in plain.splitlines():
        if line.startswith("Course full name:"):
            return line.replace("Course full name:", "").strip()
    return f"Course {course_id}"


def _delete_course_chunks(course_id: int, st: Settings) -> None:
    """Remove all vectors for course_id from both Moodle collections."""
    for col in [_get_chat_collection(st), _get_content_collection(st)]:
        try:
            col.delete(where={"course_id": course_id})
        except Exception as e:
            print(f"[Index] Delete warning course_id={course_id}: {e}")


def _index_course(course_id: int, st: Settings) -> str:
    """Embed and store course text into moodle_chat and moodle_course.

    Two passes over the same source text with different chunk sizes:
      moodle_chat:   smaller chunks (chunk_size ~800), all content
      moodle_course: larger chunks (chunk_size ~1200), learning-only

    Larger chunks for the content collection give the LLM more context per
    retrieved snippet during quiz generation and summarization.
    """
    t0 = time.monotonic()
    plain, tm = load_course_plaintext(st, course_id, skip_metadata=False)
    if not plain:
        raise RuntimeError(f"No content for course_id={course_id}")

    coursename = _coursename_from_plaintext(plain, course_id)
    print(f"[Index] Indexing course_id={course_id} ({coursename})...")
    _delete_course_chunks(course_id, st)

    # ── moodle_chat: all chunks ───────────────────────────────────────────────
    chat_chunks = chunk_text_with_overlap(plain, st.chunk_size, st.chunk_overlap, st.max_chunks)
    if not chat_chunks:
        raise RuntimeError(f"Course {course_id} produced no chat chunks")

    chat_col = _get_chat_collection(st)
    chat_embeddings = get_embeddings(st, chat_chunks)
    chat_ids = [f"chat_{course_id}_{i:04d}" for i in range(len(chat_chunks))]
    chat_metas = [{"course_id": course_id, "source": coursename, "chunk_type": "general"}
                  for _ in chat_chunks]

    for start in range(0, len(chat_chunks), 100):
        chat_col.add(
            ids=chat_ids[start:start + 100],
            embeddings=chat_embeddings[start:start + 100],
            documents=chat_chunks[start:start + 100],
            metadatas=chat_metas[start:start + 100],
        )

    # ── moodle_course: learning-only chunks ───────────────────────────────────
    content_chunks = [
        c for c in chunk_text_with_overlap(
            plain, st.quiz_chunk_size, st.quiz_chunk_overlap, st.quiz_max_chunks
        )
        if is_substantive_learning_content(c)
    ]

    content_col = _get_content_collection(st)
    if content_chunks:
        content_embeddings = get_embeddings(st, content_chunks)
        content_ids = [f"content_{course_id}_{i:04d}" for i in range(len(content_chunks))]
        content_metas = [{"course_id": course_id, "source": coursename, "chunk_type": "learning"}
                         for _ in content_chunks]
        for start in range(0, len(content_chunks), 100):
            content_col.add(
                ids=content_ids[start:start + 100],
                embeddings=content_embeddings[start:start + 100],
                documents=content_chunks[start:start + 100],
                metadatas=content_metas[start:start + 100],
            )

    _course_tm_cache[course_id] = tm
    _course_name_cache[course_id] = coursename
    redis_set_course_meta(course_id, coursename, tm)
    elapsed = time.monotonic() - t0
    print(
        f"[Index] Done course_id={course_id}: "
        f"chat={len(chat_chunks)} content={len(content_chunks)} "
        f"({elapsed:.1f}s)"
    )
    return coursename


# ─────────────────────────────────────────────────────────────────────────────
# Public entry point — called by routes and services
# ─────────────────────────────────────────────────────────────────────────────

def ensure_course_indexed(
    course_id: int,
    st: Settings | None = None,
    *,
    force_sync: bool = False,
) -> tuple[chromadb.Collection, str]:
    """Return (chat_collection, coursename). Index in background when possible.

    When ``force_sync`` is True (quiz/summarize/admin), always block until indexed.
  When ``background_course_index`` is enabled and vectors exist but are stale,
    return immediately and re-index in a background thread.
    """
    st = st or settings
    coursename, tm = _resolve_course_meta(st, course_id)
    if not coursename and tm == 0:
        raise RuntimeError(f"No content for course_id={course_id}")

    chat_col = _get_chat_collection(st)
    chunk_count = _count_where(chat_col, course_id)
    cached_tm = _course_tm_cache.get(course_id, -1)
    fresh = cached_tm == tm and chunk_count > 0

    if fresh:
        return chat_col, coursename

    use_background = bool(getattr(st, "background_course_index", True)) and not force_sync

    if chunk_count > 0 and use_background:
        schedule_course_reindex(course_id, st)
        return chat_col, coursename

    if chunk_count == 0 and use_background:
        schedule_course_reindex(course_id, st)
        raise RuntimeError(
            f"Course materials for «{coursename}» are being indexed. "
            "Please try again in about a minute."
        )

    plain, tm_plain = load_course_plaintext(st, course_id, skip_metadata=False)
    if not plain:
        raise RuntimeError(f"No content for course_id={course_id}")
    coursename = _coursename_from_plaintext(plain, course_id)
    _index_course(course_id, st)
    return _get_chat_collection(st), coursename


# ─────────────────────────────────────────────────────────────────────────────
# Cross-course search (global chat, course_id=0)
# ─────────────────────────────────────────────────────────────────────────────

def _search_one_course(
    st: Settings,
    cid: int,
    query_vec: list[float],
    per_hit: int,
    *,
    force_sync: bool,
) -> list[tuple[float, str, int, str]]:
    chat_col = _get_chat_collection(st)
    if _count_where(chat_col, cid) == 0:
        if getattr(st, "background_course_index", True) and not force_sync:
            schedule_course_reindex(cid, st)
            return []
        try:
            col, cname = ensure_course_indexed(cid, st, force_sync=True)
        except Exception:
            return []
    else:
        try:
            col, cname = ensure_course_indexed(cid, st, force_sync=force_sync)
        except Exception:
            return []

    out: list[tuple[float, str, int, str]] = []
    hits = chroma_search(col, query_vec, per_hit, where={"course_id": cid}, include_scores=True)
    for sim, text in hits:  # type: ignore[misc]
        out.append((sim, text, cid, cname))
    return out


def global_course_retrieval(
    st: Settings,
    user_id: int,
    query_vec: list[float],
    top_k: int,
) -> tuple[str, int | None, str | None]:
    """Search enrolled courses; prefer already-indexed courses, lazy-index at most N others."""
    max_courses = int(getattr(st, "cross_course_search_max", 12) or 12)
    lazy_cap = int(getattr(st, "global_lazy_index_max", 2) or 2)
    cids = list_enrolled_course_ids(st, user_id, limit=max_courses * 2)[:max_courses]
    if not cids:
        return "", None, None

    chat_col = _get_chat_collection(st)
    indexed: list[int] = []
    pending: list[int] = []
    for cid in cids:
        if _count_where(chat_col, cid) > 0:
            indexed.append(cid)
        else:
            pending.append(cid)

    per_hit = max(1, top_k // 2)
    scored: list[tuple[float, str, int, str]] = []

    for cid in indexed:
        scored.extend(_search_one_course(st, cid, query_vec, per_hit, force_sync=False))

    need_more = len(scored) < top_k and pending
    if need_more:
        for cid in pending[:lazy_cap]:
            scored.extend(_search_one_course(st, cid, query_vec, per_hit, force_sync=False))
            if len(scored) >= top_k:
                break
        for cid in pending[lazy_cap:]:
            schedule_course_reindex(cid, st)

    if not scored:
        return "", None, None

    scored.sort(key=lambda t: t[0], reverse=True)
    picked = scored[:max(1, min(top_k, 8))]
    pid, pname = picked[0][2], picked[0][3]
    blocks = [
        f"--- Course: {cn} (course_id={cid}, similarity={s:.4f}) ---\n{txt}"
        for s, txt, cid, cn in picked
    ]
    return "\n\n".join(blocks), pid, pname
