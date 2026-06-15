"""Format model replies for plain-text chat display (not document OCR)."""

from __future__ import annotations

import re

_META_TAIL_PATTERNS = (
    r"informasi ini berasal",
    r"basis pengetahuan",
    r"dokumen internal",
    r"profil perusahaan sinarmas",
    r"profil perusahaan",
    r"jika anda butuh",
    r"if you need (more|additional|further)",
    r"saya bisa bantu",
    r"i can help (you )?(find|search|look)",
    r"pengetahuan internal",
    r"knowledge base",
    r"available (course |company )?materials",
)


def _is_meta_tail_sentence(sentence: str) -> bool:
    lower = sentence.lower()
    return any(p in lower for p in _META_TAIL_PATTERNS)


def strip_trailing_meta_sentences(text: str) -> str:
    """Drop trailing disclaimer / offer-to-help sentences from model output."""
    text = (text or "").strip()
    if not text:
        return ""

    parts = re.split(r"(?<=[.!?])\s+", text)
    while len(parts) > 1 and _is_meta_tail_sentence(parts[-1]):
        parts.pop()
    return " ".join(parts).strip()


def prettify_reply(text: str) -> str:
    """Remove common markdown noise and trailing meta disclaimers for plain display."""
    if not text:
        return ""

    out = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    out = out.replace("**", " ")
    out = re.sub(r"(?<!\\)\*([^*]+)\*(?!\*)", r"\1", out)
    out = re.sub(r"^#{1,6}\s+", "", out, flags=re.MULTILINE)
    out = re.sub(r"^>\s+", "", out, flags=re.MULTILINE)
    out = re.sub(r"\n{3,}", "\n\n", out)

    return strip_trailing_meta_sentences(out.strip())
