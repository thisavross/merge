"""
quiz_engine.py
--------------
Handles quiz generation, revision, and PDF export for the chatbot.

Flow:
  1. detect_quiz_intent()     — check if user wants a quiz
  2. generate_quiz()          — produce N questions from course context
  3. revise_quiz()            — replace specific question numbers
  4. quiz_to_pdf()            — export final quiz as downloadable PDF
  5. format_quiz_for_chat()   — format quiz nicely for the chat UI

The quiz state (questions) is passed back and forth in the Moodle chat
session. The Moodle plugin stores the last quiz JSON in the chat room
metadata so the user can revise it in follow-up messages.
"""

from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path

from infrastructure.ollama_client import chat_completion
from config import settings
from prompts.quiz_prompts import (
    build_quiz_retry_reminder,
    build_quiz_system_prompt,
    build_quiz_user_message,
)

# ── Quiz intent keywords ──────────────────────────────────────────────────────
_QUIZ_KEYWORDS = (
    "kuis", "quiz", "soal", "pertanyaan", "latihan",
    "generate", "buat", "buatkan", "generate",
    "practice question", "test question", "exam question",
)

_REVISE_KEYWORDS = (
    "ganti", "ubah", "revisi", "replace", "change",
    "nomor", "no.", "soal ke", "question",
)

_SATISFIED_KEYWORDS = (
    "ya", "iya", "ok", "oke", "bagus", "puas", "setuju",
    "yes", "good", "satisfied", "download", "unduh", "pdf",
)

_NOT_SATISFIED_KEYWORDS = (
    "tidak", "belum", "kurang", "ganti", "ubah",
    "no", "not", "change", "revise", "replace",
)


# ─────────────────────────────────────────────────────────────────────────────
# Intent detection
# ─────────────────────────────────────────────────────────────────────────────

def detect_quiz_intent(question: str) -> bool:
    """Return True if the user is asking for quiz/question generation."""
    q = question.lower()
    return any(kw in q for kw in _QUIZ_KEYWORDS)


def detect_satisfied(question: str) -> bool:
    """Return True if user is happy with the quiz and wants to download."""
    q = question.lower()
    return any(kw in q for kw in _SATISFIED_KEYWORDS)


def detect_revision_intent(question: str) -> bool:
    """Return True if user wants to change specific questions."""
    q = question.lower()
    return any(kw in q for kw in _REVISE_KEYWORDS)


def extract_question_count(question: str) -> int:
    """
    Parse how many questions the user wants.
    e.g. "buat 10 soal" → 10, "5 pertanyaan" → 5
    Defaults to 5 if not specified.
    """
    match = re.search(r"\b(\d+)\b", question)
    if match:
        n = int(match.group(1))
        return max(1, min(n, 20))   # clamp between 1 and 20
    return 5


# Course/lab administration — never valid quiz stems (substring match).
_ADMIN_META_SUBSTRINGS = (
    "what is the name of this course",
    "course full name",
    "short name of the course",
    "how many weeks",
    "grading policy",
    "grading rubric",
    "attendance policy",
    "submit your assignment",
    "due date for",
    "what is this lab activity for",
    "what is this activity for",
    "objective of this lab",
    "objective of this activity",
    "purpose of this lab activity",
    "purpose of the lab activity",
    "purpose of this lab",
    "purpose of the lab",
    "tujuan dari lab ini",
    "tujuan aktivitas ini",
    "tujuan praktikum ini",
)

# Lab/assignment framing only when paired with lab|activity|assignment|course admin.
_ADMIN_META_REGEX = re.compile(
    r"(?:what is the|apa)\s+"
    r"(?:purpose|objective|tujuan)\s+"
    r"(?:of|dari)?\s*"
    r"(?:this|the|ini|tersebut)?\s*"
    r"(?:lab|activity|assignment|praktikum|tugas|course|kursus)\b",
    re.IGNORECASE,
)


def _is_meta_quiz_question(text: str) -> bool:
    """
    True only for course/lab/assignment admin questions.

    Technical questions (e.g. purpose of borders in image processing) are allowed.
    """
    t = (text or "").strip()
    if not t:
        return True
    lower = t.lower()
    if any(p in lower for p in _ADMIN_META_SUBSTRINGS):
        return True
    if _ADMIN_META_REGEX.search(t):
        return True
    return False


def _normalize_answer(raw: str) -> str | None:
    s = (raw or "").strip().upper()
    if s in ("A", "B", "C", "D"):
        return s
    m = re.search(r"\b([ABCD])\b", s)
    return m.group(1) if m else None


def _options_are_distinct(options: dict) -> bool:
    vals = [str(v).strip().lower() for v in (options or {}).values() if str(v).strip()]
    if len(vals) < 4:
        return False
    # Reject only exact duplicates (not merely similar wording).
    return len(set(vals)) == len(vals)


def _parse_quiz_json(raw: str) -> list:
    """Parse model output; tolerate markdown fences and minor truncation."""
    text = (raw or "").strip()
    text = re.sub(r"^```json\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^```\s*", "", text)
    text = re.sub(r"\s*```\s*$", "", text)
    text = text.strip()

    try:
        data = json.loads(text)
        if isinstance(data, list):
            return data
    except json.JSONDecodeError:
        pass

    # Truncated array: keep complete top-level objects only.
    start = text.find("[")
    if start < 0:
        raise ValueError("No JSON array in model output")

    decoder = json.JSONDecoder()
    idx = start + 1
    items: list = []
    while idx < len(text):
        while idx < len(text) and text[idx] in " \t\n\r,":
            idx += 1
        if idx >= len(text) or text[idx] == "]":
            break
        try:
            obj, end = decoder.raw_decode(text, idx)
            if isinstance(obj, dict):
                items.append(obj)
            idx = end
        except json.JSONDecodeError:
            break

    if items:
        return items
    raise ValueError("Could not parse quiz JSON array")


def _validate_questions(questions: list, n_questions: int) -> list[dict]:
    seen: set[str] = set()
    valid: list[dict] = []
    rejected: list[str] = []

    for q in questions:
        if not isinstance(q, dict):
            rejected.append("not a dict")
            continue
        qt = str(q.get("question", "")).strip()
        if not qt:
            rejected.append("empty question")
            continue
        if _is_meta_quiz_question(qt):
            rejected.append(f"admin/lab meta: {qt[:60]}...")
            continue
        key = qt.lower()
        if key in seen:
            rejected.append(f"duplicate: {qt[:60]}...")
            continue
        opts = q.get("options") or {}
        if not _options_are_distinct(opts):
            rejected.append(f"duplicate options: {qt[:60]}...")
            continue
        ans = _normalize_answer(str(q.get("answer", "")))
        if ans is None:
            rejected.append(f"invalid answer: {qt[:60]}...")
            continue
        q["answer"] = ans
        seen.add(key)
        valid.append(q)

    if len(valid) < n_questions:
        detail = "; ".join(rejected[:5])
        if len(rejected) > 5:
            detail += f" (+{len(rejected) - 5} more)"
        raise ValueError(
            f"Not enough valid subject-matter questions ({len(valid)}/{n_questions}). "
            f"Rejections: {detail or 'none'}"
        )

    for i, q in enumerate(valid[:n_questions]):
        q["number"] = i + 1
    return [_normalize_question_record(q) for q in valid[:n_questions]]


def _normalize_question_record(q: dict) -> dict:
    """Quiz payload: number, question, options, answer only (no explanation)."""
    opts = q.get("options") or {}
    return {
        "number": int(q.get("number", 0)),
        "question": str(q.get("question", "")).strip(),
        "options": {k: str(opts[k]).strip() for k in ("A", "B", "C", "D") if k in opts},
        "answer": str(q.get("answer", "")).strip().upper(),
    }


def _quiz_num_predict(n_questions: int) -> int:
    """Scale token budget with question count (no explanation field in output)."""
    per_q = int(getattr(settings, "quiz_tokens_per_question", 400) or 400)
    floor = int(getattr(settings, "ollama_quiz_num_predict", 12288) or 12288)
    overhead = 384
    return max(floor, n_questions * per_q + overhead, 2048)


def extract_question_numbers(question: str) -> list[int]:
    """
    Parse which question numbers the user wants to replace.
    e.g. "ganti soal nomor 3 dan 5" → [3, 5]
    e.g. "replace question 2, 4, 7" → [2, 4, 7]
    """
    return [int(m) for m in re.findall(r"\b(\d+)\b", question)]


# ─────────────────────────────────────────────────────────────────────────────
# Quiz generation
# ─────────────────────────────────────────────────────────────────────────────

def generate_quiz(
    context: str,
    coursename: str,
    n_questions: int = 5,
    language: str = "id",
    metrics_out: dict | None = None,
) -> list[dict]:
    """
    Generate N multiple-choice questions from the course context.

    Returns a list of question dicts:
    [{"number", "question", "options": {A..D}, "answer"}]
    """
    system = build_quiz_system_prompt(
        coursename, n_questions, language=language
    )
    user = build_quiz_user_message(coursename, n_questions, context)

    last_err: Exception | None = None
    raw = ""

    for attempt in range(3):
        attempt_user = user
        num_predict = _quiz_num_predict(n_questions) + (attempt * 256)
        if attempt >= 1:
            attempt_user += build_quiz_retry_reminder(n_questions)

        llm = chat_completion(
            settings,
            system,
            attempt_user,
            num_predict=num_predict,
        )
        raw = llm.text
        if metrics_out is not None:
            prev_p = int(metrics_out.get("prompt_tokens") or 0)
            prev_c = int(metrics_out.get("completion_tokens") or 0)
            prev_ms = float(metrics_out.get("llm_ms") or 0)
            metrics_out["prompt_tokens"] = prev_p + int(llm.prompt_tokens or 0)
            metrics_out["completion_tokens"] = prev_c + int(llm.completion_tokens or 0)
            metrics_out["llm_ms"] = round(prev_ms + float(llm.llm_ms or 0), 2)

        try:
            questions = _parse_quiz_json(raw)
            if not questions:
                raise ValueError("Expected non-empty JSON array")
            return _validate_questions(questions, n_questions)
        except Exception as e:
            last_err = e

    raise RuntimeError(
        f"Quiz generation failed to produce valid JSON: {last_err}\n"
        f"Raw output was:\n{raw[:1200]}"
    )

    # raw = chat_completion(settings, system, user, num_predict=max(2048, n_questions * 400),)

    # Parse JSON from model output (strip any accidental markdown fences)
    # raw = raw.strip()
    # raw = re.sub(r"^```json\s*", "", raw)
    # raw = re.sub(r"```\s*$", "", raw)
    # raw = raw.strip()

    # last_err = None
    # for attempt in range(2):
    #     raw = chat_completion(settings, system, user, num_predict=max(4096, n_questions * 500))
    #     raw = raw.strip()
    #     raw = re.sub(r"^\s*", "", raw)
    #     raw = re.sub(r"^```\s*", "", raw)
    #     raw = re.sub(r"\s$", "", raw)
    #     raw = raw.strip()
    #     try:
    #         questions = json.loads(raw)
    #         if isinstance(questions, list) and len(questions) > 0:
    #             for i, q in enumerate(questions):
    #                 q["number"] = i + 1
    #             return questions
    #     except Exception as e:
    #         last_err = e
    # raise RuntimeError(
    #     f"Quiz generation failed to produce valid JSON: {last_err}\n"
    #     f"Raw output was:\n{raw[:500]}"
    # )

    # try:
    #     questions = json.loads(raw)
    #     if not isinstance(questions, list):
    #         raise ValueError("Expected a JSON array")
    #     # Normalize numbering
    #     for i, q in enumerate(questions):
    #         q["number"] = i + 1
    #     return questions
    # except Exception as e:
    #     raise RuntimeError(
    #         f"Quiz generation failed to produce valid JSON: {e}\n"
    #         f"Raw output was:\n{raw[:500]}"
    #     )


def revise_quiz(
    existing_questions: list[dict],
    question_numbers_to_replace: list[int],
    context: str,
    coursename: str,
    language: str = "id",
    metrics_out: dict | None = None,
) -> list[dict]:
    """
    Replace specific questions in the existing quiz.
    Questions not in question_numbers_to_replace are kept as-is.
    """
    if not question_numbers_to_replace:
        return existing_questions

    n_to_replace = len(question_numbers_to_replace)
    new_questions = generate_quiz(
        context, coursename, n_to_replace, language, metrics_out=metrics_out
    )

    result = list(existing_questions)  # copy
    new_iter = iter(new_questions)

    for i, q in enumerate(result):
        if q.get("number") in question_numbers_to_replace:
            try:
                replacement = next(new_iter)
                replacement["number"] = q["number"]   # keep original number
                result[i] = replacement
            except StopIteration:
                break

    return [_normalize_question_record(q) for q in result]


# ─────────────────────────────────────────────────────────────────────────────
# Formatting for chat display
# ─────────────────────────────────────────────────────────────────────────────

def format_quiz_for_chat(questions: list[dict], coursename: str, language: str = "id") -> str:
    """
    Format quiz questions into readable plain text for the chat widget.
    No markdown bold — consistent with your system_prompt.py rules.
    """
    if language == "id":
        header = f"Berikut adalah {len(questions)} soal kuis untuk kursus {coursename}:"
        footer = (
            "\nApakah Anda puas dengan soal-soal ini?\n"
            "- Ketik 'Ya' atau 'Unduh PDF' untuk mengunduh kuis sebagai PDF.\n"
            "- Ketik 'Ganti soal nomor X' untuk mengganti soal tertentu."
        )
        answer_label = "Jawaban"
    else:
        header = f"Here are {len(questions)} quiz questions for {coursename}:"
        footer = (
            "\nAre you satisfied with these questions?\n"
            "- Type 'Yes' or 'Download PDF' to get the quiz as a PDF.\n"
            "- Type 'Replace question X' to replace specific questions."
        )
        answer_label = "Answer"

    lines = [header, ""]
    for q in questions:
        lines.append(f"{q['number']}. {q['question']}")
        opts = q.get("options", {})
        for key in ["A", "B", "C", "D"]:
            if key in opts:
                lines.append(f"   {key}. {opts[key]}")
        lines.append(f"   {answer_label}: {q.get('answer', '?')}")
        lines.append("")

    lines.append(footer)
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# PDF export
# ─────────────────────────────────────────────────────────────────────────────

def quiz_to_pdf(questions: list[dict], coursename: str, language: str = "id") -> bytes:
    """
    Generate a PDF of the quiz and return it as bytes.

    Uses only the standard library + fpdf2 (lightweight, no LaTeX needed).
    Install: pip install fpdf2

    Returns raw PDF bytes which FastAPI sends as a file download.
    """
    try:
        from fpdf import FPDF
    except ImportError:
        raise RuntimeError(
            "fpdf2 is not installed. Run: pip install fpdf2\n"
            "Then add 'fpdf2>=2.7.0' to requirements.txt"
        )

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    # Title
    pdf.set_font("Helvetica", "B", 16)
    title = f"Quiz: {coursename}" if language == "en" else f"Kuis: {coursename}"
    pdf.cell(0, 12, title, ln=True, align="C")
    pdf.ln(4)

    # Subtitle
    pdf.set_font("Helvetica", "", 10)
    subtitle = (
        f"Total questions: {len(questions)}" if language == "en"
        else f"Jumlah soal: {len(questions)}"
    )
    pdf.cell(0, 8, subtitle, ln=True, align="C")
    pdf.ln(8)

    # Questions (without answers for student version)
    pdf.set_font("Helvetica", "", 11)
    for q in questions:
        # Question text
        pdf.set_font("Helvetica", "B", 11)
        pdf.multi_cell(0, 7, f"{q['number']}. {q['question']}")
        pdf.set_font("Helvetica", "", 11)

        opts = q.get("options", {})
        for key in ["A", "B", "C", "D"]:
            if key in opts:
                pdf.multi_cell(0, 7, f"    {key}. {opts[key]}")

        pdf.ln(4)

    # Answer key on a new page
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 14)
    answer_title = "Answer Key" if language == "en" else "Kunci Jawaban"
    pdf.cell(0, 12, answer_title, ln=True, align="C")
    pdf.ln(6)

    pdf.set_font("Helvetica", "", 11)
    for q in questions:
        pdf.multi_cell(0, 7, f"{q['number']}. {q.get('answer', '?')}")
        pdf.ln(2)

    return bytes(pdf.output())


# ─────────────────────────────────────────────────────────────────────────────
# Quiz state helpers (JSON serialization for storage in Moodle DB)
# ─────────────────────────────────────────────────────────────────────────────

def quiz_to_json(questions: list[dict]) -> str:
    """Serialize quiz to JSON string for storage."""
    return json.dumps(questions, ensure_ascii=False)


def quiz_from_json(json_str: str) -> list[dict]:
    """Deserialize quiz from JSON string."""
    if not json_str:
        return []
    try:
        return json.loads(json_str)
    except Exception:
        return []