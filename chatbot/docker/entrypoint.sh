#!/bin/sh
set -e

REDIS_URL="${REDIS_URL:-redis://redis:6379/0}"
OLLAMA_BASE_URL="${OLLAMA_BASE_URL:-http://ollama:11434}"
MINIO_ENDPOINT="${MINIO_ENDPOINT:-minio:9000}"

echo "[entrypoint] Waiting for Redis at ${REDIS_URL}..."
until python -c "
import os, sys
import redis
try:
    redis.from_url(os.environ['REDIS_URL'], socket_connect_timeout=2).ping()
except Exception:
    sys.exit(1)
" 2>/dev/null; do
  sleep 2
done
echo "[entrypoint] Redis is up."

echo "[entrypoint] Waiting for Ollama at ${OLLAMA_BASE_URL}..."
until curl -sf "${OLLAMA_BASE_URL}/api/tags" >/dev/null; do
  sleep 3
done
echo "[entrypoint] Ollama is up."

echo "[entrypoint] Waiting for MinIO at ${MINIO_ENDPOINT}..."
until curl -sf "http://${MINIO_ENDPOINT}/minio/health/live" >/dev/null; do
  sleep 2
done
echo "[entrypoint] MinIO is up."

mkdir -p /app/local/chatbot/rag_service/chroma_db

echo "[entrypoint] Starting RAG service: $*"
exec "$@"
