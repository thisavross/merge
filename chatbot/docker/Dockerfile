# Moodle chatbot RAG stack — FastAPI + ChromaDB + OCR helpers
# Build from repo root: docker compose -f local/chatbot/docker/docker-compose.yml build

FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# System libs for PyMuPDF, ChromaDB, and health checks
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libmupdf-dev \
    mupdf-tools \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app/local/chatbot/rag_service

# Install Python dependencies first (better layer cache)
COPY local/chatbot/rag_service/requirements.txt ./requirements.txt
RUN pip install --upgrade pip && pip install -r requirements.txt

# Application code: RAG service + shared OCR package (bootstrap imports local/ocr)
COPY local/chatbot/docker/entrypoint.sh /app/local/chatbot/docker/entrypoint.sh
COPY local/ocr /app/local/ocr
COPY local/chatbot/rag_service /app/local/chatbot/rag_service

RUN chmod +x /app/local/chatbot/docker/entrypoint.sh

EXPOSE 8787

ENTRYPOINT ["/app/local/chatbot/docker/entrypoint.sh"]
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8787"]
