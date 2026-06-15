"""
Quiz generator prompts (spec-style). CONTEXT is passed in the user message to save tokens.
"""

from __future__ import annotations


def build_quiz_system_prompt(
    coursename: str,
    n_questions: int,
    *,
    language: str = "id",
) -> str:
    """Compact system spec; learning excerpts go in build_quiz_user_message."""
    lang = "Bahasa Indonesia" if language == "id" else "English"

    return f"""## ROLE
Academic MCQ generator for LMS. Language: {lang}.

## TASK
Produce exactly {n_questions} multiple-choice questions for subject «{coursename}» using ONLY excerpts in the user message.

## TEST (subject matter)
Concepts · definitions · methods · procedures · formulas · applications · reasoning

## FORBIDDEN (never ask about)
Course title/code · instructor · sections · schedules · grading · attendance · learning objectives metadata · lab/assignment admin ("purpose of this activity") · submission steps

## ALLOWED
Technical why/how (e.g. borders in convolution, filter purpose in image processing)

## QUALITY
Each question tests different material · Paraphrase (no verbatim copy) · 4 distinct plausible options · one correct · no trick questions · concise options

## OUTPUT
JSON array only. No markdown. No explanation field. Fields: number, question, options (A–D), answer (A|B|C|D). Complete all {n_questions} items.

## EXAMPLE (shape)
[{{"number":1,"question":"...","options":{{"A":"...","B":"...","C":"...","D":"..."}},"answer":"A"}}]"""


def build_quiz_user_message(
    coursename: str,
    n_questions: int,
    context: str,
) -> str:
    """User message: task + learning excerpts."""
    return (
        f"Generate exactly {n_questions} MCQs on the SUBJECT MATTER of «{coursename}». "
        "Output JSON only.\n\n"
        f"CONTEXT:\n{context}"
    )


def build_quiz_retry_reminder(n_questions: int) -> str:
    """Appended on retry attempts."""
    return (
        f" RETRY: Valid JSON array, exactly {n_questions} objects; "
        "fields number, question, options, answer only; four distinct options each."
    )
