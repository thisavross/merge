"""
FastAPI application entrypoint — routes only; business logic lives under services/.
"""

from __future__ import annotations

from fastapi import FastAPI

from api.routes_admin import router as admin_router
from api.routes_chat import router as chat_router

app = FastAPI(title="Moodle Chatbot RAG", version="2.2.0")
app.include_router(chat_router)
app.include_router(admin_router)
