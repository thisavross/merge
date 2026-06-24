#!/usr/bin/env bash
# Download GGUF weights from Hugging Face (gated repo — run huggingface-cli login first).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEST="${DEST:-${SCRIPT_DIR}/../models/qwen25vl-ai2d-vision}"
REPO_ID="${REPO_ID:-thisavros/qwen25-vl-model}"

mkdir -p "${DEST}"

echo "[download-qwen25vl] Destination: ${DEST}"
echo "[download-qwen25vl] Repo: ${REPO_ID}"
echo "[download-qwen25vl] If download fails, run: huggingface-cli login"

python3 - <<PY
from huggingface_hub import hf_hub_download
import os

dest = os.environ["DEST"]
repo = os.environ["REPO_ID"]
files = ["qwen25vl_ai2d-Q4_K_M.gguf", "mmproj-qwen25vl-f16.gguf"]

for name in files:
    path = hf_hub_download(repo_id=repo, filename=name, local_dir=dest)
    print(f"  OK {name} -> {path}")
PY

echo "[download-qwen25vl] Done. Run import-qwen25vl-model.sh next."
