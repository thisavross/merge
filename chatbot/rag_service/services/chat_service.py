"""Main RAG answer pipeline (general chat)."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any

from config import Settings, settings
from infrastructure.llm_result import merge_llm_metrics
from infrastructure.ollama_client import chat_completion, get_embedding
from infrastructure.redis_store import (
    append_turn,
    get_embedding_cache,
    get_history,
    get_semantic_cache,
    set_embedding_cache,
    set_semantic_cache,
    set_shared_semantic_cache, 
)
from integrations.ocr_client import split_user_attachments
from prompts.chatbot_prompts import build_system_prompt
from query_routing import is_company_focused_question
from retrieval.chroma_store import (
    chroma_search,
    chroma_search_adaptive,
    cosine_similarity,
    ensure_course_indexed,
    global_course_retrieval,
    semantic_cache_threshold,
)
from retrieval.sinarmas_retriever import search_sinarmas
from text_format import prettify_reply


_SHARED_CACHE_PROMOTE_THRESHOLD = 0.95  # module-level constant

def _check_semantic_cache(
    query_vec: list[float],
    course_id: int,
    user_id: int,
    st: Settings,
) -> tuple[str | None, float]:
    """Returns (reply, best_similarity). best_similarity=0.0 on miss."""
    threshold = semantic_cache_threshold(st)
    best_sim, best_reply = 0.0, None
    try:
        entries = get_semantic_cache(course_id, user_id)
        for entry in entries:
            cached_vec = entry.get("embedding")
            if not cached_vec:
                continue
            sim = cosine_similarity(query_vec, cached_vec)
            if sim >= threshold and sim > best_sim:
                best_sim = sim
                best_reply = entry["reply"]
        if best_reply is not None:
            scope = f"global user={user_id}" if course_id <= 0 else f"course={course_id} user={user_id}"
            print(f"[SemanticCache] HIT (similarity={best_sim:.4f}) {scope}")
    except Exception as e:
        print(f"[SemanticCache] Check failed (non-fatal): {e}")
    return best_reply, best_sim


def _store_semantic_cache(
    query_vec: list[float],
    query_text: str,
    reply: str,
    course_id: int,
    user_id: int,
) -> None:
    try:
        set_semantic_cache(course_id, user_id, query_vec, query_text, reply)
        # Also store in the shared course cache so other students benefit
        if course_id > 0:
            set_shared_semantic_cache(course_id, query_vec, query_text, reply)
        scope = f"course={course_id} user={user_id}"
        print(f"[SemanticCache] Stored reply for {scope}")
    except Exception as e:
        print(f"[SemanticCache] Store failed (non-fatal): {e}")

def _get_query_embedding(st: Settings, embed_query: str) -> list[float]:
    if getattr(st, "embed_cache_enabled", True):
        cached = get_embedding_cache(embed_query)
        if cached is not None:
            print("[EmbedCache] HIT")
            return cached
    vec = get_embedding(st, embed_query)
    if getattr(st, "embed_cache_enabled", True):
        ttl = int(getattr(st, "embed_cache_ttl_seconds", 3600) or 3600)
        set_embedding_cache(embed_query, vec, ttl=ttl)
    return vec


def _course_refer_footer(
    *,
    wwwroot: str,
    course_id: int | None,
    course_name: str,
    page_course_id: int,
    used_course_chunks: bool,
) -> str:
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


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def _history_token_budget(st: Settings) -> int:
    return int(getattr(st, "max_history_tokens", 1200) or 1200) #2400


def _trim_history_to_budget(
    history: list[dict],
    budget: int,
) -> list[dict]:
    if not history:
        return []

    kept: list[dict] = []
    total_tokens = 0
    for turn in reversed(history):
        turn_tokens = _estimate_tokens(turn.get("content", ""))
        if total_tokens + turn_tokens > budget:
            break
        kept.append(turn)
        total_tokens += turn_tokens

    return list(reversed(kept))


def _retrieve_course_context(
    st: Settings,
    course_id: int,
    user_id: int,
    query_vec: list[float],
    question: str,
    attach_text: str,
    images_b64: list[str],
) -> tuple[bool, str, str, int | None, str | None, bool]:
    """Returns (skip_course, context_body, coursename, primary_id, primary_name, used_db)."""
    skip_course = is_company_focused_question(
        question, has_attachments=bool(attach_text.strip() or images_b64)
    )
    if skip_course:
        return True, "", "this course", None, None, False

    coursename = "this course"
    course_context_body = ""
    primary_ref_id: int | None = None
    primary_ref_name: str | None = None
    used_db_course = False

    adaptive_enabled = getattr(st, "adaptive_k_enabled", True)
    adaptive_max_k = st.top_k * int(getattr(st, "adaptive_k_max_multiplier", 3))
    adaptive_min_gap = float(getattr(st, "adaptive_k_min_gap", 0.05))

    if course_id <= 0:
        uid = int(user_id or 0)
        if uid <= 1:
            raise RuntimeError("user_id required when course_id=0")
        course_context_body, primary_ref_id, primary_ref_name = global_course_retrieval(
            st, uid, query_vec, top_k=st.top_k
        )
        coursename = "your enrolled Moodle courses"
        used_db_course = bool(course_context_body.strip())
    else:
        try:
            col, coursename = ensure_course_indexed(course_id, st, force_sync=False)
            if adaptive_enabled:
                hits = chroma_search_adaptive(
                    col,
                    query_vec,
                    max_k=adaptive_max_k,
                    where={"course_id": course_id},
                    min_k=1,
                    min_gap=adaptive_min_gap,
                )
            else:
                hits = chroma_search(
                    col, query_vec, n=st.top_k, where={"course_id": course_id}
                )
            if hits:
                used_db_course = True
                primary_ref_id = course_id
                primary_ref_name = coursename
                course_context_body = "\n---\n".join(hits)  # type: ignore[arg-type]
        except Exception as e:
            print(f"[WARN] Course retrieval failed: {e}")
            raise

    return skip_course, course_context_body, coursename, primary_ref_id, primary_ref_name, used_db_course

def answer_question(
    course_id: int,
    question: str,
    attachments: list[dict] | None = None,
    *,
    page_course_id: int = 0,
    user_id: int | None = None,
    room_id: int | None = None,
    moodle_wwwroot: str = "",
    st: Settings | None = None,
    metrics_out: dict | None = None,
) -> str:
    st = st or settings
    question = (question or "").strip()
    uid = int(user_id or 0)
    rid = int(room_id or 0)  # defined early — needed by history_future below

    attach_text, images_b64 = split_user_attachments(attachments)
    if not question and not attach_text and not images_b64:
        raise RuntimeError("Empty question")

    embed_query = (
        (question + "\n\n" + attach_text)[:8000]
        if (question and attach_text)
        else question or attach_text[:8000]
    )

    # Parallel: embed query + prefetch history (neither depends on the other)
    with ThreadPoolExecutor(max_workers=2) as pre_pool:
        embed_future = pre_pool.submit(_get_query_embedding, st, embed_query)
        history_future = pre_pool.submit(get_history, uid, rid) if uid > 0 else None
        query_vec = embed_future.result()
        raw_history: list[dict] = history_future.result() if history_future else []

    # Semantic cache check — skips retrieval + LLM entirely on hit
    if not attach_text and not images_b64:
        cached_reply, _sim = _check_semantic_cache(query_vec, course_id, uid, st)
        if cached_reply is not None:
            if metrics_out is not None:
                metrics_out.update({"prompt_tokens": 0, "completion_tokens": 0, "llm_ms": 0.0})
            if uid > 0:
                try:
                    append_turn(uid, rid, "user", question)
                    append_turn(uid, rid, "assistant", cached_reply)
                except Exception:
                    pass
            return cached_reply

    global_mode = course_id <= 0
    course_result: dict[str, Any] = {}
    sinarmas_hits: list[str] = []

    # with ThreadPoolExecutor(max_workers=2) as pool:
    #     course_future = pool.submit(
    #         _retrieve_course_context,
    #         st,
    #         course_id,
    #         uid,
    #         query_vec,
    #         question,
    #         attach_text,
    #         images_b64,
    #     )
    #     sinarmas_future = pool.submit(
    #         search_sinarmas,
    #         query_vec,
    #         n=int(getattr(st, "sinarmas_top_k", 2) or 2),
    #     )
    #     try:
    #         (
    #             _skip,
    #             course_context_body,
    #             coursename,
    #             primary_ref_id,
    #             primary_ref_name,
    #             used_db_course,
    #         ) = course_future.result()
    #         course_result = {
    #             "body": course_context_body,
    #             "coursename": coursename,
    #             "primary_ref_id": primary_ref_id,
    #             "primary_ref_name": primary_ref_name,
    #             "used_db_course": used_db_course,
    #         }
    #     except Exception:
    #         course_future.cancel()
    #         raise
    #     sinarmas_hits = sinarmas_future.result()

    # course_context_body = course_result.get("body", "")
    # coursename = course_result.get("coursename", "this course")
    # primary_ref_id = course_result.get("primary_ref_id")
    # primary_ref_name = course_result.get("primary_ref_name")
    # used_db_course = bool(course_result.get("used_db_course"))
    (
    _skip,
    course_context_body,
    coursename,
    primary_ref_id,
    primary_ref_name,
    used_db_course,
    ) = _retrieve_course_context(
        st,
        course_id,
        uid,
        query_vec,
        question,
        attach_text,
        images_b64,
    )

    _adaptive_enabled = getattr(st, "adaptive_k_enabled", True)
    _adaptive_min_gap = float(getattr(st, "adaptive_k_min_gap", 0.05))
    sinarmas_hits = search_sinarmas(
        query_vec,
        n=int(getattr(st, "sinarmas_top_k", 4) or 4),
        adaptive=_adaptive_enabled,
        adaptive_multiplier=int(getattr(st, "adaptive_k_max_multiplier", 3)),
        adaptive_min_gap=_adaptive_min_gap,
    )

    context_parts: list[str] = []
    if str(course_context_body).strip():
        context_parts.append("=== COURSE CONTENT ===")
        context_parts.append(str(course_context_body).strip())
    if sinarmas_hits:
        context_parts.append("=== PT SMART TBK / SINARMAS GENERAL KNOWLEDGE ===")
        context_parts.append("\n---\n".join(sinarmas_hits))
    if attach_text.strip():
        context_parts.append("=== ATTACHED FILE ===")
        context_parts.append(attach_text.strip())

    context = "\n\n".join(context_parts)
    if not context.strip():
        raise RuntimeError("No context available — check course index and Sinarmas index.")

    # raw_history already fetched in pre_pool above — just trim it
    history_budget = _history_token_budget(st)
    history = _trim_history_to_budget(raw_history, budget=history_budget)
    if len(raw_history) != len(history):
        print(
            f"[History] Trimmed {len(raw_history)} → {len(history)} turns "
            f"to stay within {history_budget} token budget"
        )

    system = build_system_prompt(coursename, context, global_course_mode=global_mode)

    user_parts = []
    if question:
        user_parts.append(question)
    if attach_text:
        user_parts.append("Attached file content:\n" + attach_text)
    user_message = "\n\n".join(user_parts).strip() or (
        "Describe what is relevant in the attached image."
    )

    vision_model = (st.ollama_vision_model or "").strip() or st.ollama_chat_model
    llm_result = (
        chat_completion(
            st,
            system,
            user_message,
            images=images_b64,
            model=vision_model,
            history=history,
            guardrail_query=question,
        )
        if images_b64
        else chat_completion(
            st,
            system,
            user_message,
            history=history,
            guardrail_query=question,
        )
    )
    if metrics_out is not None:
        merge_llm_metrics(metrics_out, llm_result)

    reply = prettify_reply(llm_result.text)

    if not attach_text and not images_b64 and uid > 0:
        _store_semantic_cache(query_vec, question, reply, course_id, uid)

    if uid > 0:
        try:
            append_turn(uid, rid, "user", user_message)
            append_turn(uid, rid, "assistant", reply)
        except Exception as e:
            print(f"[History] Append failed (non-fatal): {e}")

    footer = _course_refer_footer(
        wwwroot=moodle_wwwroot,
        course_id=primary_ref_id,
        course_name=(primary_ref_name or "").strip(),
        page_course_id=max(0, int(page_course_id or 0)),
        used_course_chunks=used_db_course,
    )
    return (reply.rstrip() + footer) if (footer and reply) else (footer.strip() if footer else reply)