# Moodle chatbot RAG stack — FastAPI + ChromaDB + OCR helpers
# Build from repo root: docker compose -f local/chatbot/docker/docker-compose.yml build

FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# System libs for PyMuPDF, ChromaDB, OpenCV, and health checks
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libglib2.0-0 \
    libgl1 \
    libgomp1 \
    libsm6 \
    libxcb1 \
    libxext6 \
    libxrender1 \
    libmupdf-dev \
    mupdf-tools \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app/local/chatbot/rag_service

# Install Python dependencies first (better layer cache)
COPY local/chatbot/rag_service/requirements.txt ./requirements.txt
COPY local/chatbot/rag_service/requirements-ocr.txt ./requirements-ocr.txt
RUN pip install --upgrade pip \
    && pip install -r requirements.txt \
    && pip install -r requirements-ocr.txt \
    && pip uninstall -y opencv-python opencv-contrib-python 2>/dev/null || true \
    && pip install --force-reinstall "opencv-python-headless>=4.8.0" \
    && python -c "import cv2; print('cv2 build check', cv2.__version__)"

# Application code: RAG service + shared OCR package (bootstrap imports local/ocr)
COPY local/chatbot/docker/entrypoint.sh /app/local/chatbot/docker/entrypoint.sh
COPY local/ocr /app/local/ocr
COPY local/chatbot/rag_service /app/local/chatbot/rag_service

RUN chmod +x /app/local/chatbot/docker/entrypoint.sh

EXPOSE 8787

ENTRYPOINT ["/app/local/chatbot/docker/entrypoint.sh"]
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8787"]
