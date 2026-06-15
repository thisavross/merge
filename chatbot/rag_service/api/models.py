"""Pydantic request/response models for the FastAPI layer."""

from __future__ import annotations

from pydantic import BaseModel, Field


class AttachmentIn(BaseModel):
    name: str = ""
    mime: str = ""
    data_base64: str = ""


class ChatRequest(BaseModel):
    question: str = ""
    course_id: int = Field(0, ge=0)
    page_course_id: int = Field(0, ge=0)
    user_id: int | None = None
    room_id: int = Field(0, ge=0)
    moodle_wwwroot: str = ""
    language: str = "id"
    pending_quiz_json: str = ""
    force_quiz: bool = False
    attachments: list[AttachmentIn] | None = None


class ResponseMetrics(BaseModel):
    """Included in /chat JSON for debugging (curl, Swagger). Moodle UI does not read this."""

    route: str = ""
    response_time_ms: float = 0.0
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    llm_ms: float | None = None
    embed_ms: float | None = None
    retrieval_ms: float | None = None


class ChatResponse(BaseModel):
    reply: str = ""
    error: str | None = None
    quiz_json: str = ""
    quiz_ready_for_pdf: bool = False
    metrics: ResponseMetrics | None = None


class QuizPdfRequest(BaseModel):
    quiz_json: str
    coursename: str = "Course"
    language: str = "id"


class ClearHistoryRequest(BaseModel):
    user_id: int
    room_id: int = 0


class CourseReindexRequest(BaseModel):
    course_id: int = Field(..., gt=1)
    sync: bool = Field(
        False,
        description="If true, block until indexing finishes. Default: background job.",
    )
