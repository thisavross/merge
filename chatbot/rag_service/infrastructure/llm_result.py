"""Structured result from an Ollama /api/chat call."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ChatCompletionResult:
    text: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    llm_ms: float | None = None

    @property
    def total_tokens(self) -> int | None:
        if self.prompt_tokens is None and self.completion_tokens is None:
            return None
        return int(self.prompt_tokens or 0) + int(self.completion_tokens or 0)


def metrics_from_llm(result: ChatCompletionResult) -> dict:
    """Flatten LLM usage for API metrics JSON."""
    return {
        "prompt_tokens": result.prompt_tokens,
        "completion_tokens": result.completion_tokens,
        "total_tokens": result.total_tokens,
        "llm_ms": round(result.llm_ms, 2) if result.llm_ms is not None else None,
    }


def merge_llm_metrics(into: dict, result: ChatCompletionResult | None) -> None:
    """Copy token fields from ChatCompletionResult into a metrics accumulator."""
    if result is None:
        return
    into.update(metrics_from_llm(result))
