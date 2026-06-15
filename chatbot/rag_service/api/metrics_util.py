"""Build and log API response metrics (FastAPI/Swagger only — Moodle ignores extra fields)."""

from __future__ import annotations

import json
import time
from typing import Any

from api.models import ResponseMetrics


def start_timer() -> float:
    return time.perf_counter()


def build_response_metrics(
    route: str,
    t0: float,
    *,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    llm_ms: float | None = None,
    embed_ms: float | None = None,
    retrieval_ms: float | None = None,
) -> ResponseMetrics:
    total_ms = round((time.perf_counter() - t0) * 1000, 2)
    total_tokens: int | None = None
    if prompt_tokens is not None or completion_tokens is not None:
        total_tokens = int(prompt_tokens or 0) + int(completion_tokens or 0)

    return ResponseMetrics(
        route=route,
        response_time_ms=total_ms,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        llm_ms=round(llm_ms, 2) if llm_ms is not None else None,
        embed_ms=round(embed_ms, 2) if embed_ms is not None else None,
        retrieval_ms=round(retrieval_ms, 2) if retrieval_ms is not None else None,
    )


def log_response_metrics(metrics: ResponseMetrics | None) -> None:
    if metrics is None:
        return
    print(f"[Metrics] {json.dumps(metrics.model_dump(exclude_none=True), ensure_ascii=False)}")
