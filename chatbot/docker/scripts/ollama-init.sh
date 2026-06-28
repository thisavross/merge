#!/bin/sh
# Pull models into the shared ollama_data volume (profile: init-models).
set -e

OLLAMA_HOST="${OLLAMA_HOST:-http://ollama:11434}"
EMBED="${OLLAMA_EMBED_MODEL:-bge-m3}"
CHAT="${OLLAMA_CHAT_MODEL:-qwen3_q4km:latest}"
VISION="${OLLAMA_VISION_MODEL:-}"

echo "[ollama-init] Host: ${OLLAMA_HOST}"

until OLLAMA_HOST="${OLLAMA_HOST}" ollama list >/dev/null 2>&1; do
  echo "[ollama-init] Waiting for Ollama..."
  sleep 3
done

pull() {
  model="$1"
  if [ -z "$model" ]; then
    return 0
  fi
  echo "[ollama-init] Pulling ${model}..."
  if ollama pull "$model" 2>&1; then
    echo "[ollama-init] OK: ${model}"
  else
    echo "[ollama-init] SKIP: ${model} not in registry (import manually via ollama create)"
  fi
}

export OLLAMA_HOST
pull "$EMBED"
pull "$CHAT"
pull "$VISION"

echo "[ollama-init] Done."
