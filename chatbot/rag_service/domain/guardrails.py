"""Out-of-scope request detection and canned replies (no I/O)."""

from __future__ import annotations

import re

GUARDRAIL_REPLY = (
    "Maaf, sebagai asisten Moda, saya didesain khusus untuk membantu proses pembelajaran "
    "materi kursus dan regulasi perusahaan. Saya tidak diizinkan untuk menyediakan kode "
    "pemrograman, script, atau pembuatan website."
)

_FORBIDDEN_REQUEST_PHRASES = (
    "create web",
    "make website",
    "buat web",
    "bikin web",
    "generate website",
    "write code",
    "buatkan kode",
    "minta kode",
    "berikan code",
    "tampilkan kode",
    "bikin aplikasi",
    "create app",
    "generate code",
    "buat program",
    "build a calculator",
    "buat kalkulator",
    "tolong buat script",
    "buatkan script",
)


def resolve_guardrail_query(user: str, guardrail_query: str | None) -> str:
    """Use the real user question, not RAG/summarize context appended to the user message."""
    if guardrail_query is not None:
        return guardrail_query.strip()
    head = (user or "").split("\n\n", 1)[0].strip()
    return head[:800]


def user_request_asks_for_new_code(text: str) -> bool:
    q = (text or "").lower().strip()
    if not q:
        return False
    return any(p in q for p in _FORBIDDEN_REQUEST_PHRASES)


def response_contains_unsolicited_code(text: str) -> bool:
    """Block only when the model outputs a full code dump, not course quotes in prose."""
    if "<?php" in text:
        return True
    return bool(re.search(r"```(?:\w+)?\s*\n[\s\S]{30,}?\n```", text))
