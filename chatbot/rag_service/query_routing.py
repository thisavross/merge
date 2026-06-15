"""Lightweight routing: skip heavy course index for company-only questions."""

from __future__ import annotations

_COMPANY_HINTS = (
    "sinarmas",
    "pt smart",
    "smart tbk",
    "direktur",
    "komisaris",
    "ceo",
    "presiden",
    "visi",
    "misi",
    "perusahaan",
    "sustainability",
    "kelapa sawit",
    "palm oil",
    "margarin",
    "oleochemical",
    "bioenergy",
    "governance",
    "csr",
    "hr ",
    "human resources",
)


def is_company_focused_question(question: str, *, has_attachments: bool) -> bool:
    """
    True when the question is likely answerable from Sinarmas general knowledge only.
    Skips building the course FAISS index (major latency win on cold cache).
    """
    if has_attachments:
        return False
    q = (question or "").strip().lower()
    if len(q) < 3:
        return False
    return any(hint in q for hint in _COMPANY_HINTS)
