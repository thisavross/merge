"""
infrastructure/ollama_client.py
────────────────────────────────
Minimal Ollama HTTP client — embeddings and chat completion.

RESPONSIBILITIES:
  1. get_embedding(settings, text)          → list[float]
  2. get_embeddings(settings, texts)        → list[list[float]]  (batch, 1 HTTP call)
  3. chat_completion(settings, system, user, ...)  → ChatCompletionResult

CONTEXT-AWARE CONVERSATION:
  chat_completion accepts an optional `history` parameter.
  When provided, history turns are injected between the system message and the
  current user message, giving Ollama full conversational context.

  Message structure sent to /api/chat:
    [system]
    [history turn 1 user]
    [history turn 1 assistant]
    ...
    [current user message]   ← with optional vision images

STREAMING:
  We use httpx's streaming client and accumulate content chunks.
  This avoids a timeout when the model takes >30s to generate (common on CPU).

GUARDRAILS:
  Out-of-scope requests (code generation, web building) are blocked BEFORE
  any tokens reach the LLM. Logic lives in domain.guardrails so it can be
  unit-tested independently of the HTTP layer.
"""

from __future__ import annotations

import json
import re
import time
import typing as t

import httpx

from infrastructure.llm_result import ChatCompletionResult

if t.TYPE_CHECKING:
    from config import Settings

from domain.guardrails import (
    GUARDRAIL_REPLY,
    resolve_guardrail_query,
    response_contains_unsolicited_code,
    user_request_asks_for_new_code,
)


def _client(timeout: float = 300.0) -> httpx.Client:
    """Default 300s — summarize with large context can exceed 120s on CPU."""
    return httpx.Client(timeout=timeout)


def _parse_embed_response(data: dict, index: int = 0) -> list[float]:
    """Extract the embedding vector from an Ollama /api/embed response."""
    if "embeddings" in data and isinstance(data["embeddings"], list) and data["embeddings"]:
        vec = data["embeddings"][index] if index < len(data["embeddings"]) else data["embeddings"][0]
        if isinstance(vec, list):
            return [float(x) for x in vec]
    emb = data.get("embedding")
    if isinstance(emb, list):
        return [float(x) for x in emb]
    raise RuntimeError("Ollama embed response missing embeddings field")


# ─────────────────────────────────────────────────────────────────────────────
# Embedding
# ─────────────────────────────────────────────────────────────────────────────

def get_embedding(settings: Settings, text: str) -> list[float]:
    """Embed a single text string.

    Tries /api/embed (Ollama 0.3+) and falls back to /api/embeddings (older releases).
    """
    base = settings.ollama_base_url.rstrip("/")
    text = (text or "").strip()
    if not text:
        raise RuntimeError("Ollama embed input is empty")

    with _client() as c:
        r = c.post(base + "/api/embed", json={"model": settings.ollama_embed_model, "input": text})
        if r.status_code in (404, 400):
            r2 = c.post(
                base + "/api/embeddings",
                json={"model": settings.ollama_embed_model, "prompt": text},
            )
            if r2.status_code < 400:
                r = r2
        try:
            r.raise_for_status()
        except httpx.HTTPStatusError:
            body = ""
            try:
                body = r.text
            except Exception:
                pass
            raise RuntimeError(f"Ollama embed failed (HTTP {r.status_code}): {body[:500]}")
        return _parse_embed_response(r.json(), 0)


def get_embeddings(settings: Settings, texts: list[str]) -> list[list[float]]:
    """Batch-embed multiple texts in a single HTTP call when possible.

    Falls back to serial get_embedding() when the batch endpoint is not supported
    or when the response structure doesn't match expectations.
    """
    texts = [t for t in texts if (t or "").strip()]
    if not texts:
        return []
    if len(texts) == 1:
        return [get_embedding(settings, texts[0])]

    base = settings.ollama_base_url.rstrip("/")
    with _client() as c:
        r = c.post(base + "/api/embed", json={"model": settings.ollama_embed_model, "input": texts})
        if r.status_code in (404, 400):
            return [get_embedding(settings, t) for t in texts]
        try:
            r.raise_for_status()
        except httpx.HTTPStatusError:
            return [get_embedding(settings, t) for t in texts]
        data = r.json()

    if "embeddings" in data and isinstance(data["embeddings"], list):
        if len(data["embeddings"]) == len(texts):
            return [[float(x) for x in vec] for vec in data["embeddings"]]

    return [get_embedding(settings, t) for t in texts]


# ─────────────────────────────────────────────────────────────────────────────
# Chat completion
# ─────────────────────────────────────────────────────────────────────────────

def chat_completion(
    settings: Settings,
    system: str,
    user: str,
    images: list[str] | None = None,
    model: str | None = None,
    history: list[dict] | None = None,
    num_predict: int | None = None,
    guardrail_query: str | None = None,
    options_extra: dict[str, t.Any] | None = None,
) -> ChatCompletionResult:
    """POST /api/chat and return text plus Ollama token usage when available.

    Parameters
    ----------
    system         : System prompt (RAG context + instructions).
    user           : Current user message (may include retrieved excerpts appended).
    images         : Base64-encoded images for vision models.
    model          : Override the configured chat model.
    history        : Previous turns [{role, content}, ...] from redis_store.get_history().
                     Injected between system and current user message.
    num_predict    : Token cap for this call (overrides settings.ollama_chat_num_predict).
    guardrail_query: The raw user question (before RAG context is appended), used to
                     check the guardrail without triggering on course text that mentions
                     programming.
    options_extra  : Extra Ollama options dict (e.g. {"repeat_penalty": 1.18}).
    """
    # ── Guardrail: block before any token hits the LLM ────────────────────────
    if user_request_asks_for_new_code(resolve_guardrail_query(user, guardrail_query)):
        return ChatCompletionResult(text=GUARDRAIL_REPLY, prompt_tokens=0, completion_tokens=0, llm_ms=0.0)

    url = settings.ollama_base_url.rstrip("/") + "/api/chat"

    # ── Build message list ────────────────────────────────────────────────────
    messages: list[dict] = []
    if system:
        messages.append({"role": "system", "content": system})
    if history:
        for turn in history:
            role = turn.get("role", "user")
            content = turn.get("content", "")
            if role in ("user", "assistant") and content:
                messages.append({"role": role, "content": content})
    user_msg: dict = {"role": "user", "content": user}
    if images:
        user_msg["images"] = images
    messages.append(user_msg)

    # ── Generation options ────────────────────────────────────────────────────
    options: dict[str, t.Any] = {
        "temperature": float(getattr(settings, "ollama_chat_temperature", 0.0) or 0.0),
        "min_p": 0.05,          # replaces top_p at low temperature — faster sampling
        "top_k": 20,            # limits candidate pool, speeds up each token
        "top_p": 1.0,           # effectively disabled — min_p takes over
        "num_ctx": int(getattr(settings, "ollama_chat_num_ctx", 4096) or 4096),
        "num_thread": int(getattr(settings, "ollama_num_thread", 4) or 4),
        "think": False,
    }
    effective_num_predict = int(
        num_predict or getattr(settings, "ollama_chat_num_predict", 2048) or 2048
    )
    options["num_predict"] = max(effective_num_predict, 512)
    options["num_thread"] = int(getattr(settings, "ollama_num_thread", 4) or 4)

    if options_extra:
        options.update(options_extra)

    # ── Streaming accumulation ────────────────────────────────────────────────
    t0 = time.perf_counter()
    full_content = ""
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    with _client() as c:
        with c.stream(
            "POST",
            url,
            json={
                "model": model or settings.ollama_chat_model,
                "messages": messages,
                "stream": True,
                "options": options,
            },
        ) as r:
            try:
                r.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise RuntimeError(
                    f"Ollama HTTP error ({r.status_code}). "
                    f"Check that the model is loaded."
                ) from exc

            for line in r.iter_lines():
                if not line.strip():
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if "error" in data:
                    raise RuntimeError(f"Ollama engine error: {data['error']}")
                full_content += (data.get("message") or {}).get("content", "")
                if data.get("done"):
                    prompt_tokens = data.get("prompt_eval_count")
                    completion_tokens = data.get("eval_count")

    llm_ms = (time.perf_counter() - t0) * 1000

    if not full_content:
        raise RuntimeError("Ollama returned empty content.")

    # ── Post-generation guardrail ─────────────────────────────────────────────
    if response_contains_unsolicited_code(full_content):
        print("[GUARDRAIL ALERT] LLM output contained an unsolicited code block.")
        return ChatCompletionResult(
            text=GUARDRAIL_REPLY,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            llm_ms=llm_ms,
        )

    # Strip qwen3 chain-of-thought tags if present (in case think=False is ignored).
    full_content = re.sub(r"<think>.*?</think>", "", full_content, flags=re.DOTALL).strip()

    return ChatCompletionResult(
        text=full_content,
        prompt_tokens=int(prompt_tokens) if prompt_tokens is not None else None,
        completion_tokens=int(completion_tokens) if completion_tokens is not None else None,
        llm_ms=llm_ms,
    )