"""Chat and history routes."""

from __future__ import annotations

import traceback
from typing import Any

from fastapi import APIRouter, Header, HTTPException

from api.metrics_util import build_response_metrics, log_response_metrics, start_timer
from api.models import ChatRequest, ChatResponse, ClearHistoryRequest
from config import settings
from infrastructure.redis_store import clear_all_history, clear_history
from retrieval.chroma_store import ensure_course_indexed
from retrieval.course_retriever import retrieve_quiz_context, retrieve_summarize_context
from services.chat_service import answer_question
from services.quiz_service import (
    detect_quiz_intent,
    detect_revision_intent,
    detect_satisfied,
    extract_question_count,
    extract_question_numbers,
    format_quiz_for_chat,
    generate_quiz,
    quiz_from_json,
    quiz_to_json,
    revise_quiz,
)
from services.summary_service import detect_summarize_intent, generate_course_summary

router = APIRouter()


def _effective_course_id(body: ChatRequest) -> int:
    """Moodle may send course_id=0 from the dashboard while page_course_id is set."""
    cid = int(body.course_id or 0)
    if cid > 0:
        return cid
    pc = int(body.page_course_id or 0)
    return pc if pc > 0 else 0


def _check_secret(x_chatbot_secret: str | None) -> None:
    if settings.chatbot_secret and (x_chatbot_secret or "") != settings.chatbot_secret:
        raise HTTPException(
            status_code=401, detail="Invalid or missing X-Chatbot-Secret"
        )


def _finish(
    t0: float,
    route: str,
    *,
    reply: str = "",
    error: str | None = None,
    quiz_json: str = "",
    quiz_ready_for_pdf: bool = False,
    llm_metrics: dict[str, Any] | None = None,
) -> ChatResponse:
    lm = llm_metrics or {}
    metrics = build_response_metrics(
        route,
        t0,
        prompt_tokens=lm.get("prompt_tokens"),
        completion_tokens=lm.get("completion_tokens"),
        llm_ms=lm.get("llm_ms"),
    )
    log_response_metrics(metrics)
    return ChatResponse(
        reply=reply,
        error=error,
        quiz_json=quiz_json,
        quiz_ready_for_pdf=quiz_ready_for_pdf,
        metrics=metrics,
    )


@router.post("/chat", response_model=ChatResponse)
def chat(
    body: ChatRequest,
    x_chatbot_secret: str | None = Header(default=None, alias="X-Chatbot-Secret"),
) -> ChatResponse:
    _check_secret(x_chatbot_secret)
    print("=== CHAT DEBUG ===")
    print("USER ID:", body.user_id)
    print("COURSE ID:", body.course_id)
    print("PAGE COURSE ID:", body.page_course_id)
    print("QUESTION:", body.question)

    t0 = start_timer()
    llm_metrics: dict[str, Any] = {}

    question = (body.question or "").strip()
    language = (body.language or "id").strip().lower()
    pending_questions = quiz_from_json(body.pending_quiz_json)
    course_id = _effective_course_id(body)

    try:
        if pending_questions:
            if detect_satisfied(question):
                msg = (
                    "Kuis siap diunduh! Klik tombol 'Unduh PDF' di bawah."
                    if language == "id"
                    else "Quiz is ready! Click the 'Download PDF' button below."
                )
                return _finish(
                    t0,
                    "quiz_ready",
                    reply=msg,
                    quiz_json=quiz_to_json(pending_questions),
                    quiz_ready_for_pdf=True,
                )

            if detect_revision_intent(question):
                numbers = extract_question_numbers(question)
                if not numbers:
                    msg = (
                        "Soal nomor berapa yang ingin diganti? Contoh: 'Ganti soal nomor 3 dan 5'"
                        if language == "id"
                        else "Which question numbers should I replace? Example: 'Replace questions 3 and 5'"
                    )
                    return _finish(
                        t0,
                        "quiz_revision_prompt",
                        reply=msg,
                        quiz_json=quiz_to_json(pending_questions),
                    )

                _, coursename = ensure_course_indexed(
                    course_id, settings, force_sync=True
                )
                context = retrieve_quiz_context(
                    course_id,
                    coursename,
                    settings,
                    user_question=question,
                )
                revised = revise_quiz(
                    pending_questions,
                    numbers,
                    context,
                    coursename,
                    language,
                    metrics_out=llm_metrics,
                )
                reply = format_quiz_for_chat(revised, coursename, language)
                return _finish(
                    t0,
                    "quiz_revise",
                    reply=reply,
                    quiz_json=quiz_to_json(revised),
                    llm_metrics=llm_metrics,
                )

            reply = format_quiz_for_chat(pending_questions, "course", language)
            return _finish(
                t0,
                "quiz_pending",
                reply=reply,
                quiz_json=quiz_to_json(pending_questions),
            )

        if body.force_quiz or detect_quiz_intent(question):
            n = extract_question_count(question)

            if course_id <= 0:
                return _finish(
                    t0,
                    "quiz_no_course",
                    reply=(
                        "Silakan buka halaman kursus terlebih dahulu untuk membuat kuis."
                        if language == "id"
                        else "Please open a course page first to generate a quiz."
                    ),
                )

            _, coursename = ensure_course_indexed(course_id, settings, force_sync=True)
            context = retrieve_quiz_context(
                course_id,
                coursename,
                settings,
                user_question=question,
            )

            if not context:
                return _finish(
                    t0,
                    "quiz_no_context",
                    reply=(
                        "Materi kursus belum tersedia untuk dijadikan soal kuis."
                        if language == "id"
                        else "Course materials are not available yet to generate quiz questions."
                    ),
                )

            questions = generate_quiz(
                context, coursename, n, language, metrics_out=llm_metrics
            )
            reply = format_quiz_for_chat(questions, coursename, language)
            return _finish(
                t0,
                "quiz",
                reply=reply,
                quiz_json=quiz_to_json(questions),
                llm_metrics=llm_metrics,
            )

        if detect_summarize_intent(question):
            if course_id <= 0:
                return _finish(
                    t0,
                    "summarize_no_course",
                    reply=(
                        "Silakan buka halaman kursus terlebih dahulu untuk merangkum materi kursus."
                        if language == "id"
                        else "Please open a course page first to summarize the course content."
                    ),
                )

            _, coursename = ensure_course_indexed(course_id, settings, force_sync=True)
            context = retrieve_summarize_context(
                course_id,
                coursename,
                settings,
                user_question=question,
            )

            if not context:
                return _finish(
                    t0,
                    "summarize_no_context",
                    reply=(
                        "Materi kursus belum tersedia untuk dirangkum."
                        if language == "id"
                        else "Course materials are not available yet to summarize."
                    ),
                )

            reply = generate_course_summary(
                context,
                coursename,
                language=language,
                user_question=question,
                metrics_out=llm_metrics,
            )
            return _finish(
                t0,
                "summarize",
                reply=reply,
                llm_metrics=llm_metrics,
            )

        atts = (
            [
                {"name": a.name, "mime": a.mime, "data_base64": a.data_base64}
                for a in body.attachments
            ]
            if body.attachments
            else None
        )
        reply = answer_question(
            course_id,
            question,
            atts,
            page_course_id=course_id
            if course_id > 0
            else int(body.page_course_id or 0),
            user_id=body.user_id,
            room_id=int(body.room_id or 0),
            moodle_wwwroot=(body.moodle_wwwroot or "").strip(),
            metrics_out=llm_metrics,
        )
        return _finish(t0, "chat", reply=reply, llm_metrics=llm_metrics)

    except Exception as e:
        traceback.print_exc()
        return _finish(t0, "error", reply="", error=f"{type(e).__name__}: {e}")


@router.delete("/chat/history")
def delete_chat_history(body: ClearHistoryRequest) -> dict:
    if not body.user_id:
        raise HTTPException(status_code=400, detail="user_id required")
    if not body.room_id:
        raise HTTPException(
            status_code=400, detail="room_id required for single-room delete"
        )

    deleted = clear_history(body.user_id, body.room_id)
    return {"deleted": deleted, "user_id": body.user_id, "room_id": body.room_id}


@router.delete("/chat/history/all")
def delete_all_chat_history(body: ClearHistoryRequest) -> dict:
    if not body.user_id:
        raise HTTPException(status_code=400, detail="user_id required")

    deleted = clear_all_history(body.user_id)
    return {"deleted": deleted, "user_id": body.user_id}
