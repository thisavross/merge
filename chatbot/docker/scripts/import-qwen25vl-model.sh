#!/bin/sh
# Register custom Qwen2.5-VL vision model from local GGUF (not on ollama.com registry).
set -e

OLLAMA_HOST="${OLLAMA_HOST:-http://ollama:11434}"
MODEL_DIR="${MODEL_DIR:-/models/qwen25vl}"
MODEL_NAME="${MODEL_NAME:-qwen25vl-ai2d-vision}"

export OLLAMA_HOST

if ollama list 2>/dev/null | grep -q "${MODEL_NAME}"; then
  echo "[import-qwen25vl] ${MODEL_NAME} already exists — skip"
  exit 0
fi

if [ ! -f "${MODEL_DIR}/qwen25vl_ai2d-Q4_K_M.gguf" ] || [ ! -f "${MODEL_DIR}/mmproj-qwen25vl-f16.gguf" ]; then
  echo "[import-qwen25vl] Missing GGUF in ${MODEL_DIR}/"
  echo "  Expected: qwen25vl_ai2d-Q4_K_M.gguf and mmproj-qwen25vl-f16.gguf"
  exit 1
fi

if [ ! -f "${MODEL_DIR}/Modelfile" ]; then
  echo "[import-qwen25vl] Missing ${MODEL_DIR}/Modelfile"
  exit 1
fi

echo "[import-qwen25vl] Creating ${MODEL_NAME} from ${MODEL_DIR}..."
cd "${MODEL_DIR}"
ollama create "${MODEL_NAME}" -f Modelfile
echo "[import-qwen25vl] Done."
