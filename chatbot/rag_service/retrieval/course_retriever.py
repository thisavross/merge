"""
retrieval/course_retriever.py
─────────────────────────────
Public retrieval functions for quiz, summarization, and general chat.

These functions are the only interface that services/ and api/ should call.
They do NOT import private helpers from chroma_store — only the public API.

Token-budget helpers (summarize_excerpt_token_budget, trim_excerpt_context_for_llm)
live here because they are pure functions of the context text and settings,
not of Chroma state.
"""

from __future__ import annotations

from config import Settings, settings
from infrastructure.ollama_client import get_embedding
from retrieval.chroma_store import (
    chroma_search,
    dedupe_chunks,
    ensure_course_indexed,
    get_content_documents,
    get_learning_chunks_for_summary,
    global_course_retrieval,
    rank_chunks_for_quiz,
    _get_chat_collection,
    _get_course_documents,
)

# Sentinel used by trim_excerpt_context_for_llm to locate the excerpt body.
_EXCERPT_MARKER = "=== LEARNING MATERIAL (excerpts) ===\n"


# ─────────────────────────────────────────────────────────────────────────────
# Token-budget helpers
# ─────────────────────────────────────────────────────────────────────────────

def summarize_excerpt_token_budget(
    st: Settings | None = None,
    *,
    reserve_tokens: int = 1800,
    output_tokens: int | None = None,
) -> int:
    """Return the maximum excerpt token count that fits in the Ollama context window.

    Formula:  budget = num_ctx − reserve_tokens − output_tokens

    reserve_tokens covers the system prompt, headers, and overhead.
    Without this cap, a 30-chunk summarize context silently overflows num_ctx
    and the model only sees the header, producing a generic reply.
    """
    st = st or settings
    num_ctx = int(getattr(st, "ollama_chat_num_ctx", 8192) or 8192)
    out_tok = (
        int(output_tokens)
        if output_tokens is not None
        else int(getattr(st, "ollama_summarize_num_predict", 2048) or 2048)
    )
    safe = max(2000, num_ctx - reserve_tokens - out_tok)
    custom = int(getattr(st, "summarize_max_context_tokens", 0) or 0)
    return min(custom, safe) if custom > 0 else safe


def trim_excerpt_context_for_llm(
    context: str,
    st: Settings | None = None,
    *,
    reserve_tokens: int = 1800,
    output_tokens: int | None = None,
    budget_tokens_override: int | None = None,
) -> str:
    """Trim the excerpt block so the full prompt fits within ollama_chat_num_ctx.

    Strategy:
      - Split on the EXCERPT_MARKER sentinel to separate header from body.
      - Body chunks are separated by '\\n\\n---\\n\\n'.
      - Keep as many chunks as fit within budget_chars (budget_tokens × 4).
      - If no chunks fit, keep at least 500 chars of the body as a safety fallback.
      - Append a note telling the LLM how many chunks were omitted.
    """
    st = st or settings
    budget_tokens = (
        int(budget_tokens_override)
        if budget_tokens_override is not None
        else summarize_excerpt_token_budget(st, reserve_tokens=reserve_tokens,
                                             output_tokens=output_tokens)
    )
    budget_chars = budget_tokens * 4

    if len(context) <= budget_chars:
        return context

    if _EXCERPT_MARKER in context:
        header, body = context.split(_EXCERPT_MARKER, 1)
        header = header + _EXCERPT_MARKER
    else:
        header, body = "", context

    parts = [p.strip() for p in body.split("\n\n---\n\n") if p.strip()]
    kept: list[str] = []
    used = len(header)
    for part in parts:
        extra = len(part) + (len("\n\n---\n\n") if kept else 0)
        if used + extra > budget_chars:
            break
        kept.append(part)
        used += extra

    if not kept and body:
        kept = [body[:max(500, budget_chars - len(header))]]

    omitted = len(parts) - len(kept)
    note = (
        f"\n\n[{omitted} additional excerpt(s) omitted to fit the context window; "
        "summarize from the excerpts above.]\n"
        if omitted > 0
        else ""
    )
    trimmed = "\n\n---\n\n".join(kept)
    print(
        f"[Summarize] Trimmed context {len(context)} → {len(header) + len(trimmed)} chars "
        f"({len(kept)}/{len(parts)} chunks, budget≈{budget_tokens} tokens)"
    )
    return header + trimmed + note


# ─────────────────────────────────────────────────────────────────────────────
# Course link footer (injected after the answer when the user is on the
# dashboard and the best matching course is not the current page)
# ─────────────────────────────────────────────────────────────────────────────

def course_refer_footer(
    *,
    wwwroot: str,
    course_id: int | None,
    course_name: str,
    page_course_id: int,
    used_course_chunks: bool,
) -> str:
    """Return a Markdown link to the source course, or empty string.

    Only shown when:
      - Course chunks were actually used in the answer.
      - The matched course_id is not the current page (page_course_id).
      - wwwroot is configured so the URL is valid.
    """
    if not used_course_chunks or course_id is None or int(course_id) <= 1:
        return ""
    if int(page_course_id or 0) > 1:
        return ""
    wwwroot = (wwwroot or "").rstrip("/")
    if not wwwroot:
        return ""
    url = f"{wwwroot}/course/view.php?id={int(course_id)}"
    label = (course_name or "").strip() or str(course_id)
    return f"\n\nPlease refer to [{label}]({url}) for more."


# ─────────────────────────────────────────────────────────────────────────────
# Core retrieval — used by quiz, summarize, and content-heavy tasks
# ─────────────────────────────────────────────────────────────────────────────

def retrieve_course_content_context(
    course_id: int,
    coursename: str,
    st: Settings | None = None,
    *,
    user_question: str = "",
    max_chunks: int | None = None,
    allow_chat_fallback: bool = False,
    header: str = "",
) -> str:
    """Retrieve substantive learning material from moodle_course.

    Flow:
      1. Embed a content-biased query (course name + user question).
      2. Fetch all stored content chunks for this course (with their embeddings).
      3. Re-rank by cosine similarity, filtering out assignment/instruction chunks.
      4. Optionally fall back to moodle_chat when content chunks are sparse.
      5. Return a header + deduplicated chunk text for the LLM prompt.

    Why re-rank locally instead of relying on Chroma's query()?
      Chroma's query() returns top-K by similarity to a single query vector.
      _rank_chunks_for_quiz also filters on content_filter.is_substantive_learning_content(),
      which Chroma cannot do. The local re-rank is O(N) over a small N (≤60 chunks),
      so it's fast.
    """
    st = st or settings
    ensure_course_indexed(course_id, st)

    subject_hint = (coursename or "").strip() or f"course {course_id}"
    retrieval_query = (
        f"Core subject matter and technical concepts taught in {subject_hint}. "
        f"Topics, definitions, algorithms, methods, formulas, and worked examples. "
        f"User request: {(user_question or 'course content').strip()}"
    )
    q_vec = get_embedding(st, retrieval_query)
    max_ctx = max_chunks if max_chunks is not None else int(
        getattr(st, "quiz_context_chunks", 10) or 10
    )

    ranked = rank_chunks_for_quiz(
        get_content_documents(course_id, st, include_embeddings=True),
        q_vec,
        max_ctx * 2,
    )

    if allow_chat_fallback and len(ranked) < max(3, max_ctx // 2):
        chat_col = _get_chat_collection(st)
        extra = rank_chunks_for_quiz(
            _get_course_documents(chat_col, course_id, include_embeddings=True),
            q_vec,
            max_ctx * 2,
        )
        ranked = dedupe_chunks(ranked + extra, max_ctx * 2)

    if not ranked:
        return ""

    body = "\n\n---\n\n".join(dedupe_chunks(ranked, max_ctx))
    if not header:
        header = (
            f"=== COURSE: {subject_hint} (course_id={course_id}) ===\n"
            "=== LEARNING MATERIAL (excerpts) ===\n"
        )
    return header + body


def retrieve_quiz_context(
    course_id: int,
    coursename: str,
    st: Settings | None = None,
    *,
    user_question: str = "",
) -> str:
    """Retrieve learning context for quiz generation.

    Wraps retrieve_course_content_context with a quiz-specific header that
    instructs the LLM to produce concept/method questions, not meta-questions.
    """
    st = st or settings
    subject_hint = (coursename or "").strip() or f"course {course_id}"
    header = (
        f"=== COURSE: {subject_hint} (course_id={course_id}) ===\n"
        "The quiz MUST test the SUBJECT MATTER and technical concepts in the material below "
        f"(discipline/topics of «{subject_hint}»).\n"
        "FORBIDDEN question types: purpose of a lab, what this activity is for, assignment "
        "instructions, course name, section titles, schedules, or grading.\n"
        "REQUIRED: questions about concepts, methods, definitions, procedures, and applications "
        "explained in the excerpts.\n\n"
        "=== LEARNING MATERIAL (excerpts) ===\n"
    )
    return retrieve_course_content_context(
        course_id, coursename, st,
        user_question=user_question,
        max_chunks=int(getattr(st, "quiz_context_chunks", 10) or 10),
        allow_chat_fallback=True,
        header=header,
    )


def retrieve_summarize_context(
    course_id: int,
    coursename: str,
    st: Settings | None = None,
    *,
    user_question: str = "",
) -> str:
    """Retrieve ALL learning chunks for course summarization.

    Unlike quiz retrieval (top-K similarity search), summarization fetches
    every learning chunk for the course so the LLM can give a comprehensive
    overview rather than one biased toward the 'summarize' query vector.

    The chunks are sorted longest-first to put the densest material at the
    top of the prompt, maximising information per token before the budget trim.
    """
    st = st or settings
    ensure_course_indexed(course_id, st)

    subject_hint = (coursename or "").strip() or f"course {course_id}"
    max_chunks = int(getattr(st, "summarize_context_chunks", 30) or 30)

    chunks = get_learning_chunks_for_summary(course_id, st)

    if not chunks:
        print(f"[Summarize] No learning chunks for course_id={course_id}, falling back to moodle_chat")
        chat_col = _get_chat_collection(st)
        all_chat = _get_course_documents(chat_col, course_id, include_embeddings=False)
        chunks = [
            doc for doc, _ in all_chat
            if doc and str(doc).strip() and len(str(doc).split()) >= 20
        ]

    if not chunks:
        print(f"[Summarize] No chunks at all for course_id={course_id}")
        return ""

    original_count = len(chunks)
    chunks = sorted(chunks, key=len, reverse=True)
    chunks = dedupe_chunks(chunks, max_chunks)
    print(
        f"[Summarize] course_id={course_id}: "
        f"original={original_count} → deduped={len(chunks)} chunks (budget={max_chunks})"
    )

    header = (
        f"=== COURSE: {subject_hint} (course_id={course_id}) ===\n"
        "Summarize ONLY the subject-matter in the excerpts below.\n"
        "Focus on: concepts, techniques, methods, and topics actually taught.\n"
        "Do NOT mention course structure, labs, assignments, or Moodle metadata.\n\n"
        "=== LEARNING MATERIAL (excerpts) ===\n"
    )
    body = "\n\n---\n\n".join(chunks)
    print(f"[Summarize] Final context: {len(body)} chars, {len(chunks)} chunks")
    return header + body