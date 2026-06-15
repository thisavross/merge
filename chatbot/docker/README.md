# Moodle Chatbot — Docker Compose Stack

**Bahasa Indonesia (tutorial lengkap):** [README.id.md](./README.id.md)

Runs the full RAG backend and its dependencies:

| Service | Image / build | Role |
|---------|----------------|------|
| **rag** | `Dockerfile` in this folder | FastAPI RAG (`uvicorn`), ChromaDB, PyMySQL, OCR via `local/ocr` |
| **ollama** | `ollama/ollama` | Local LLM + embeddings (`bge-m3`, chat model, optional vision) |
| **redis** | `redis:7-alpine` | Multi-turn history + semantic answer cache |
| **minio** | `minio/minio` | PDF object storage for Sinarmas knowledge index |
| **minio-init** | `minio/mc` | Creates bucket on first start |

**Moodle (PHP/MAMP) stays on the host.** Point the plugin `fastapiurl` to `http://127.0.0.1:8787`.

## Prerequisites

- Docker Desktop (Mac) or Docker Engine + Compose v2
- Moodle MySQL reachable from containers (`host.docker.internal` on Mac)
- Host path to Moodle **dataroot** (for course file extraction)

## Quick start

From the **Moodle repo root** (`moodle500/`):

```bash
cp local/chatbot/docker/.env.example local/chatbot/docker/.env
# Edit .env: MYSQL_PASSWORD, MOODLE_DATAROOT_HOST, models, etc.

chmod +x local/chatbot/docker/start.sh
./local/chatbot/docker/start.sh up -d --build
```

Pull Ollama models (first time, large download):

```bash
docker compose -f local/chatbot/docker/docker-compose.yml --env-file local/chatbot/docker/.env --profile init-models run --rm ollama-init
```

Or manually:

```bash
docker exec -it moodle-chatbot-ollama ollama pull bge-m3
docker exec -it moodle-chatbot-ollama ollama pull qwen3_q4km:latest
```

Health check:

```bash
curl http://127.0.0.1:8787/health
```

Build Sinarmas Chroma index (after uploading PDFs to MinIO console `http://127.0.0.1:9001`):

```bash
docker exec -it moodle-chatbot-rag python scripts/build_sinarmas_index.py
```

## Moodle configuration

1. Site administration → Plugins → Local plugins → **Chatbot**
2. Set **FastAPI URL** to `http://127.0.0.1:8787`
3. If `CHATBOT_SECRET` is set in `.env`, match it in Moodle plugin settings

## Volumes (persistent data)

| Volume | Contents |
|--------|----------|
| `rag_chroma` | ChromaDB vectors (`moodle_chat`, `moodle_course`, `sinarmas_knowledge`) |
| `ollama_data` | Downloaded models |
| `minio_data` | PDF files |
| `redis_data` | AOF Redis persistence |

Host bind (read-only): `${MOODLE_DATAROOT_HOST}` → `/moodle/dataroot` inside **rag**.

## Tech stack inside the **rag** image

- **API:** FastAPI, Uvicorn, Pydantic Settings  
- **DB:** PyMySQL → host MySQL (Moodle)  
- **Vectors:** ChromaDB, NumPy, FAISS-CPU  
- **Cache:** Redis (client)  
- **LLM:** HTTP → Ollama (`httpx`)  
- **Objects:** MinIO Python SDK  
- **Documents:** PyMuPDF, pypdf, python-docx, python-pptx, openpyxl, fpdf2  
- **OCR path:** `local/ocr` (PDF/Office extraction, vision page images)

## Common commands

```bash
# Logs
docker compose -f local/chatbot/docker/docker-compose.yml logs -f rag

# Stop
docker compose -f local/chatbot/docker/docker-compose.yml down

# Stop and remove volumes (wipes Chroma + models + MinIO)
docker compose -f local/chatbot/docker/docker-compose.yml down -v
```

## Linux note

If `host.docker.internal` does not resolve, set `MYSQL_HOST` to your host LAN IP or add `extra_hosts` in `docker-compose.yml` (already included for Desktop).
