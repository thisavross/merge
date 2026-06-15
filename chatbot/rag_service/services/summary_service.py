"""
course_summarize.py
-------------------
Detect "summarize this course" intent and produce a summary from full course
material (same indexing/retrieval path as quiz generation).
"""

from __future__ import annotations

import re
from difflib import get_close_matches

from config import settings
from text_format import prettify_reply
from infrastructure.ollama_client import chat_completion
from infrastructure.llm_result import ChatCompletionResult
from prompts.chatbot_prompts import (
    build_course_summary_system_prompt,
    build_course_summary_user_message,
)
from retrieval.course_retriever import (
    retrieve_summarize_context,
    summarize_excerpt_token_budget,
    trim_excerpt_context_for_llm,
)
from infrastructure.redis_store import get_summary_cache, set_summary_cache

_SUMMARIZE_KEYWORDS = (
    "summarize this course",
    "summarize the course",
    "summarize course",
    "course summary",
    "ringkas kursus",
    "ringkasan kursus",
    "rangkum kursus",
    "rangkuman kursus",
    "buat ringkasan",
    "buatkan ringkasan",
    "summary of this course",
    "summarize",
    "ringkas",
    "ringkasan",
    "rangkum",
    "rangkuman",
    "sumarize", "summrize", "smmurize",
    "ringkaskan", "ringkasin", "rangkumin",
    "merangkum", "meringkas",
    "bikinin ringkasan", "buatin ringkasan",
    "kasih ringkasan", "kasih rangkuman",
)

_QUIZ_BLOCKERS = (
    "kuis",
    "quiz",
    "soal",
    "pertanyaan",
    "latihan",
    "practice question",
    "test question",
    "exam question",
)


_SECTION_MARKERS = (
    "topik yang dipelajari",
    "topics covered",
    "metode & tools",
    "methods & tools",
    "gambaran singkat",
    "brief overview",
    "yang akan kamu kuasai",
    "what you will master",
    # heading dinamis akan dideteksi lewat pola ## di sanitizer
)

_PLACEHOLDER_MARKERS = (
    "[bullet:",
    "[max 6 bullets]",
    "theme or concept from excerpts",
    "libraries/tools grouped",
    "2–3 sentences max describing",
    "(bullets)",
    "(4–5 sentences",
    "(3–4 bullets",
    "[nama topik]",
    "[topic]",
)

_BRIEF_SIGNALS = (
    "seringkas mungkin", "singkat saja", "singkat", "pendek",
    "tldr", "tl;dr", "brief", "short", "quickly", "cepat",
    "garis besar", "intinya saja", "pokoknya",
    "singkt", "pendek aja", "ringkaskan", "ringkasin",
    "sesingkat", "disingkat", "dipersingkat",
)

_DETAILED_SIGNALS = (
    "detail", "lengkap", "komprehensif", "mendalam", "thorough",
    "panjang", "selengkapnya", "semua", "explain everything",
    "jelaskan semua", "secara lengkap", "secara detail",
    "detil", "detal", "lengkapp", "komplit", "complete",
    "jelasin semua", "jelasin detail",
)


_SUMMARIZE_NUM_PREDICT_CAP = 1500


def _looks_like_template_output(text: str) -> bool:
    t = (text or "").lower()
    return any(m in t for m in _PLACEHOLDER_MARKERS)


def sanitize_course_summary(
    text: str,
    *,
    max_bullets_per_section: int = 8,
    max_chars: int = 5000,
) -> str:
    """Drop duplicate bullets and cap length. Section headings detected by ## prefix."""
    lines = (text or "").splitlines()
    out: list[str] = []
    seen: set[str] = set()
    section_bullets = 0
    in_prose_section = False  # True for Overview and non-bullet sections

    for line in lines:
        stripped = line.strip()
        low = stripped.lower()

        # Detect any ## heading as a section boundary
        is_heading = stripped.startswith("##")
        is_known_marker = any(m in low for m in _SECTION_MARKERS)

        if (is_heading or is_known_marker) and not low.startswith("- "):
            section_bullets = 0
            # Overview/Gambaran/Brief sections are prose — don't filter bullets there
            in_prose_section = any(
                m in low for m in (
                    "gambaran", "overview", "cara kerja", "how it works",
                    "cara menerapkan", "how to apply", "apa itu", "what is",
                    "penerapan", "application",
                )
            )
            out.append(line)
            continue

        if stripped.startswith("- "):
            if in_prose_section:
                # Allow bullets in prose sections (they're valid content)
                out.append(line)
                continue
            key = re.sub(r"\s+", " ", stripped[2:].strip().lower())
            if key in seen or section_bullets >= max_bullets_per_section:
                continue
            seen.add(key)
            section_bullets += 1

        out.append(line)
        if len("\n".join(out)) > max_chars:
            break

    return "\n".join(out).strip()

def _fuzzy_contains(text: str, keywords: tuple, cutoff: float = 0.82) -> bool:
    """Return True if any keyword is close enough to any word/phrase in text."""
    words = text.split()
    for kw in keywords:
        kw_words = kw.split()
        if len(kw_words) == 1:
            if get_close_matches(kw, words, n=1, cutoff=cutoff):
                return True
        else:
            if kw in text:
                return True
            matches = sum(1 for w in kw_words if get_close_matches(w, words, n=1, cutoff=cutoff))
            if matches >= len(kw_words) * 0.75:
                return True
    return False


def detect_summarize_intent(question: str) -> bool:
    q = (question or "").lower().strip()
    if not q:
        return False
    if any(kw in q for kw in _QUIZ_BLOCKERS):
        return False
    if any(kw in q for kw in _SUMMARIZE_KEYWORDS):
        return True
    return _fuzzy_contains(q, _SUMMARIZE_KEYWORDS, cutoff=0.82)

def _detect_summary_style(question: str) -> str:
    q = (question or "").lower()
    if any(s in q for s in _BRIEF_SIGNALS) or _fuzzy_contains(q, _BRIEF_SIGNALS, cutoff=0.85):
        return "brief"
    if any(s in q for s in _DETAILED_SIGNALS) or _fuzzy_contains(q, _DETAILED_SIGNALS, cutoff=0.85):
        return "detailed"
    return "standard"

def generate_course_summary(
    context: str,
    coursename: str,
    *,
    course_id: int = 0,
    language: str = "id",
    user_question: str = "",
    metrics_out: dict | None = None,
) -> str:
    style = _detect_summary_style(user_question)  # sambungkan style detection

    if course_id > 0:
        cached = get_summary_cache(course_id, language, style)  # tambah style
        if cached:
            print(f"[SummaryCache] HIT course_id={course_id} lang={language} style={style}")
            if metrics_out is not None:
                metrics_out.update({"prompt_tokens": 0, "completion_tokens": 0, "llm_ms": 0.0})
            return cached

    if not context.strip():
        return (
            "Maaf, tidak ada materi kursus yang tersedia untuk dirangkum."
            if language == "id"
            else "Sorry, no course material is available to summarize."
        )

    system = build_course_summary_system_prompt(coursename, language=language)

    # num_predict varies by style
    _style_predict = {"brief": 400, "standard": 1200, "detailed": 1500}
    num_predict = min(
        _style_predict.get(style, int(getattr(settings, "ollama_summarize_num_predict", 1200) or 1200)),
        _SUMMARIZE_NUM_PREDICT_CAP,
    )

    excerpt_budget = summarize_excerpt_token_budget(settings, output_tokens=num_predict)

    print(f"[Summarize] style={style} | num_predict={num_predict} | num_ctx={settings.ollama_chat_num_ctx}")
    print(f"[Summarize] excerpt token budget={excerpt_budget}")

    def _call_llm(ctx: str) -> ChatCompletionResult:
        user = build_course_summary_user_message(
            coursename, ctx,
            language=language,
            style=style,                          # sambungkan style
            user_question=user_question,
        )
        print(
            f"[Summarize] system={len(system)} chars | user={len(user)} chars | "
            f"context={len(ctx)} chars"
        )
        return chat_completion(
            settings,
            system,
            user,
            num_predict=num_predict,
            guardrail_query=(user_question or "").strip(),
            options_extra={
                "repeat_penalty": 1.18,
                "repeat_last_n": 128,
                "temperature": 0.25,
            },
        )

    def _accumulate_llm(llm: ChatCompletionResult) -> str:
        if metrics_out is not None:
            prev_p = int(metrics_out.get("prompt_tokens") or 0)
            prev_c = int(metrics_out.get("completion_tokens") or 0)
            prev_ms = float(metrics_out.get("llm_ms") or 0)
            metrics_out["prompt_tokens"] = prev_p + int(llm.prompt_tokens or 0)
            metrics_out["completion_tokens"] = prev_c + int(llm.completion_tokens or 0)
            metrics_out["llm_ms"] = round(prev_ms + float(llm.llm_ms or 0), 2)
        return llm.text

    trimmed = trim_excerpt_context_for_llm(context, settings, output_tokens=num_predict)
    raw = _accumulate_llm(_call_llm(trimmed))

    print(f"[Summarize] raw reply = {len(raw)} chars | preview: {raw[:120]!r}")

    result = sanitize_course_summary(prettify_reply(raw), max_bullets_per_section=8, max_chars=5000)
    if _looks_like_template_output(result):
        print("[Summarize] Rejected template-like output; retrying once")
        raw = _accumulate_llm(_call_llm(trimmed))
        result = sanitize_course_summary(prettify_reply(raw), max_bullets_per_section=8, max_chars=5000)

    if not result or len(result.strip()) < 20:
        half_budget = max(2000, excerpt_budget // 2)
        tighter = trim_excerpt_context_for_llm(
            context, settings,
            output_tokens=num_predict,
            budget_tokens_override=half_budget,
        )
        if len(tighter) < len(trimmed):
            print(f"[Summarize] Retrying with tighter context {len(trimmed)} → {len(tighter)} chars")
            raw = _accumulate_llm(_call_llm(tighter))
            print(f"[Summarize] retry raw reply = {len(raw)} chars | preview: {raw[:120]!r}")
            result = sanitize_course_summary(prettify_reply(raw), max_bullets_per_section=8, max_chars=5000)

    if not result or len(result.strip()) < 20:
        print(f"[Summarize] WARNING: reply suspiciously short: {result!r}")
        return (
            "Maaf, gagal menghasilkan ringkasan. Coba lagi."
            if language == "id"
            else "Sorry, failed to generate a summary. Please try again."
        )

    if course_id > 0:
        set_summary_cache(course_id, language, result, style)  # tambah style
        print(f"[SummaryCache] Stored course_id={course_id} lang={language} style={style}")

    return result