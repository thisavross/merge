"""
build_sinarmas_index.py
-----------------------
Builds the Sinarmas ChromaDB knowledge index with cosine similarity.

PDF source priority:
  1. MinIO (if running) — all .pdf files in the bucket
  2. Local fallback — rawinfosmart.pdf next to this script

Run whenever:
  - First setup
  - New PDF uploaded to MinIO
  - PDF content updated

Usage:
    cd local/chatbot/rag_service
    source .venv/bin/activate
    python build_sinarmas_index.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import chromadb

sys.path.append(str(Path(__file__).resolve().parents[1]))

from config import settings

from infrastructure.minio_client import (
    download_pdf_bytes,
    is_minio_available,
    list_pdfs,
)
from infrastructure.ollama_client import get_embedding
from integrations.ocr_client import extract_document_bytes

CHROMA_PATH = Path(__file__).resolve().parents[1] / "chroma_db"
COLLECTION_NAME = "sinarmas_knowledge"
# LOCAL_PDF_PATH = (
#     Path(__file__).resolve().parents[1] / r"chatbot\rag_service\ocr_sample.pdf"
# )
# Use an absolute path to your PDF
LOCAL_PDF_PATH = Path(
    r"C:\Users\asus\Documents\aiocrchatbotplugin\chatbot\rag_service\ocr_sample.pdf"
)


def load_all_pdf_texts() -> list[tuple[str, str]]:
    results: list[tuple[str, str]] = []

    if is_minio_available():
        print("[INFO] MinIO running — loading PDFs from bucket...")
        pdf_names = list_pdfs()
        if not pdf_names:
            print(
                f"[WARN] No PDFs in bucket '{settings.minio_bucket}'. Falling back to local."
            )
        else:
            print(f"[INFO] Found {len(pdf_names)} PDF(s): {pdf_names}")
            for name in pdf_names:
                try:
                    data = download_pdf_bytes(name)
                    text = extract_document_bytes(name, data, "application/pdf")
                    if text.strip():
                        results.append((name, text))
                        print(f"  ✓ {name}: {len(text):,} chars")
                    else:
                        print(f"  ✗ {name}: no text (scanned? needs OCR)")
                except Exception as e:
                    print(f"  ✗ {name}: {e}")
            if results:
                return results
    else:
        print("[INFO] MinIO not running — using local file fallback.")

    if not LOCAL_PDF_PATH.exists():
        print(f"[ERROR] {LOCAL_PDF_PATH} not found.")
        sys.exit(1)

    data = LOCAL_PDF_PATH.read_bytes()
    text = extract_document_bytes(LOCAL_PDF_PATH.name, data, "application/pdf")
    if not text.strip():
        print("[ERROR] No text extracted. Scanned PDF needs OCR first.")
        sys.exit(1)

    results.append((LOCAL_PDF_PATH.name, text))
    print(f"[INFO] Local '{LOCAL_PDF_PATH.name}': {len(text):,} chars")
    return results


def clean_text(text: str) -> str:
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def chunk_text(
    text: str, source_name: str, chunk_size: int = 600, overlap: int = 100
) -> list[dict]:
    text = clean_text(text)
    chunks: list[dict] = []
    step = max(chunk_size - overlap, 50)
    for i in range(0, len(text), step):
        piece = text[i : i + chunk_size].strip()
        if piece:
            chunks.append({"text": piece, "source": source_name})
    return chunks


def build() -> None:
    pdf_texts = load_all_pdf_texts()
    if not pdf_texts:
        print("[ERROR] No usable PDF text.")
        sys.exit(1)

    all_chunks: list[dict] = []
    for source_name, text in pdf_texts:
        chunks = chunk_text(text, source_name)
        all_chunks.extend(chunks)
        print(f"[INFO] '{source_name}' → {len(chunks)} chunks")

    total = len(all_chunks)
    print(f"[INFO] Total: {total} chunks from {len(pdf_texts)} PDF(s)")

    CHROMA_PATH.mkdir(exist_ok=True)
    client = chromadb.HttpClient(
        host=settings.chroma_host,
        port=settings.chroma_port,
    )

    # Delete and recreate with cosine similarity
    existing = [c.name for c in client.list_collections()]
    if COLLECTION_NAME in existing:
        print(f"[INFO] Deleting old '{COLLECTION_NAME}' collection...")
        client.delete_collection(COLLECTION_NAME)

    # Create with cosine similarity — same as rag_engine.py
    collection = client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )

    print(f"[INFO] Embedding {total} chunks via {settings.ollama_embed_model}...")
    print("       bge-m3 is thorough — please wait a few minutes.")

    BATCH = 50
    ids: list[str] = []
    embeddings: list[list[float]] = []
    documents: list[str] = []
    metadatas: list[dict] = []

    for i, chunk in enumerate(all_chunks):
        vec = get_embedding(settings, chunk["text"])
        ids.append(f"smart_{i:05d}")
        embeddings.append(vec)
        documents.append(chunk["text"])
        metadatas.append({"source": chunk["source"]})

        if (i + 1) % 10 == 0 or (i + 1) == total:
            print(f"  ... {i + 1}/{total}")

        if len(ids) >= BATCH:
            collection.add(
                ids=ids, embeddings=embeddings, documents=documents, metadatas=metadatas
            )
            ids, embeddings, documents, metadatas = [], [], [], []

    if ids:
        collection.add(
            ids=ids, embeddings=embeddings, documents=documents, metadatas=metadatas
        )

    print(
        f"\n[DONE] {collection.count()} entries in '{COLLECTION_NAME}' (cosine similarity)."
    )
    print(f"       Path: {CHROMA_PATH}")


if __name__ == "__main__":
    build()
