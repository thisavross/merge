"""
FastAPI application entrypoint — routes only; business logic lives under services/.
"""

from __future__ import annotations

import threading

from fastapi import FastAPI

from api.routes_admin import router as admin_router
from api.routes_chat import router as chat_router

app = FastAPI(title="Moodle Chatbot RAG", version="2.2.0")
app.include_router(chat_router)
app.include_router(admin_router)


def _warmup_ollama() -> None:
    """Pre-load the LLM into Ollama RAM so the first real query is not delayed.

    Runs in a background thread at startup.  A failure here is non-fatal — the
    service still starts, and the model will be loaded on the first real request.
    """
    try:
        from config import settings
        from infrastructure.ollama_client import chat_completion

        print("[Warmup] Pre-loading LLM model into Ollama…")
        chat_completion(
            settings,
            system="",
            user="hi",
            num_predict=1,
        )
        print("[Warmup] LLM model ready.")
    except Exception as e:
        print(f"[Warmup] Non-fatal warmup error (model will load on first query): {e}")


def _maybe_rebuild_sinarmas() -> None:
    """Auto-index MinIO PDFs into sinarmas_knowledge if the collection is empty."""
    import time
    try:
        from retrieval.chroma_store import _get_sinarmas_collection
        col = _get_sinarmas_collection()
        if col is None or col.count() == 0:
            print("[Startup] sinarmas_knowledge is empty — triggering rebuild from MinIO…")
            from services.index_service import run_sinarmas_rebuild
            run_sinarmas_rebuild()
            print("[Startup] sinarmas_knowledge rebuild complete.")
        else:
            print(f"[Startup] sinarmas_knowledge has {col.count()} chunks — skipping rebuild.")
    except Exception as e:
        print(f"[Startup] Non-fatal sinarmas rebuild error: {e}")


@app.on_event("startup")
def _on_startup() -> None:
    threading.Thread(target=_maybe_rebuild_sinarmas, daemon=True, name="sinarmas-rebuild").start()
    # Warmup starts after a short delay so sinarmas rebuild gets CPU first.
    def _delayed_warmup() -> None:
        import time
        time.sleep(5)
        _warmup_ollama()
    threading.Thread(target=_delayed_warmup, daemon=True, name="ollama-warmup").start()
