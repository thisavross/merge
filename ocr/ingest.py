import os
from pathlib import Path

import chromadb
import hashlib
from retrieval.chroma_store import _get_client
from extract import preview_chunks, process_pdf, save_jsonl

client = _get_client()

document_collection = client.get_or_create_collection(
    name="document_index",
    metadata={"hnsw:space": "cosine"},
)

chunk_collection = client.get_or_create_collection(
    name="rag_chunks",
    metadata={"hnsw:space": "cosine"},
)

EMBED_BATCH_SIZE = 16
MAX_DOC_REPR_CHUNKS = 25
embedding_model = os.getenv("EMBED_MODEL_NAME", "bge-m3")


def stable_id(text):
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def safe_text(text):
    if text is None:
        return ""
    return str(text).strip()


def safe_section(section):
    if not section:
        return None
    section = str(section).strip()
    if not section:
        return None
    return section


def safe_block_type(block_type):
    if not block_type:
        return "text"
    return str(block_type).strip().lower()


def get_chunk_type(chunk):
    return safe_block_type(chunk.get("type") or chunk.get("block_type"))


def format_bge_document(text):
    text = safe_text(text)
    return f"passage: {text}"


def format_bge_query(text):
    text = safe_text(text)
    return f"query: {text}"


def embed_texts(
    texts,
    batch_size=EMBED_BATCH_SIZE,
):
    if not texts:
        return []

    embeddings = embedding_model.encode(
        texts,
        batch_size=batch_size,
        normalize_embeddings=True,
        show_progress_bar=True,
    )

    return embeddings.tolist()


def build_document_representation(chunks):

    if not chunks:
        return ""

    selected_chunks = []
    seen_sections = set()

    sorted_chunks = sorted(
        chunks,
        key=lambda x: (
            0 if get_chunk_type(x) == "table" else 1,
            x.get("page", 0),
        ),
    )

    for chunk in sorted_chunks:
        content = safe_text(chunk.get("content"))

        if not content:
            continue

        section = safe_section(chunk.get("section"))

        block_type = get_chunk_type(chunk)

        prefix = []

        if section and section not in seen_sections:
            prefix.append(f"[SECTION] {section}")
            seen_sections.add(section)

        prefix.append(f"[TYPE] {block_type}")

        text = "\n".join(prefix)
        text += "\n"

        if block_type == "table":
            text += content[:1200]
        else:
            text += content[:500]

        selected_chunks.append(text)

        if len(selected_chunks) >= MAX_DOC_REPR_CHUNKS:
            break

    return "\n\n".join(selected_chunks)


def enrich_chunk_text(chunk):

    content = safe_text(chunk.get("content"))

    if not content:
        return ""

    section = safe_section(chunk.get("section"))

    block_type = get_chunk_type(chunk)

    enriched = []

    if section:
        enriched.append(f"Section: {section}")

    enriched.append(f"Content Type: {block_type}")

    if block_type == "table":
        enriched.append("Structured Financial Table")

    enriched.append(content)

    return "\n".join(enriched)


def ingest_pdf(
    pdf_path,
    course_id=None,
    source_type="student_upload",
):
    print(f"\nProcessing: {pdf_path.name}")

    processed = process_pdf(str(pdf_path))

    doc_id = processed.get("doc_id")

    if not doc_id:
        doc_id = stable_id(f"{source_type}_{pdf_path.name}")

    chunks = processed.get("chunks", [])

    if not chunks:
        print("No chunks found")
        return

    doc_text = build_document_representation(chunks)

    if not doc_text:
        print("Document representation empty")
        return

    print("Embedding document...")

    doc_embedding = embed_texts([format_bge_document(doc_text)])[0]

    total_tables = sum(1 for c in chunks if get_chunk_type(c) == "table")

    document_collection.upsert(
        ids=[doc_id],
        documents=[doc_text],
        embeddings=[doc_embedding],
        metadatas=[
            {
                "doc_id": doc_id,
                "source": source_type,
                "course_id": course_id or -1,
                "document_name": pdf_path.stem,
                "source_pdf": pdf_path.name,
                "total_chunks": len(chunks),
                "total_tables": total_tables,
            }
        ],
    )

    chunk_docs = []
    embed_inputs = []
    chunk_ids = []
    chunk_metas = []

    seen_ids = set()

    for c in chunks:
        raw_chunk = safe_text(c.get("content"))

        if not raw_chunk:
            continue

        enriched_chunk = enrich_chunk_text(c)

        page = int(c.get("page", 0) or 0)

        section = safe_section(c.get("section"))

        block_type = get_chunk_type(c)

        metadata = c.get("metadata",{},)

        tsr_tokens = metadata.get("tsr_tokens",[],)

        bbox = metadata.get("bbox",None,)

        chunk_index = metadata.get("chunk_index",0,)
        token_count = metadata.get("token_count",0,)
        chunk_id = stable_id(f"{doc_id}_{chunk_index}_{raw_chunk[:300]}")

        if chunk_id in seen_ids:
            continue

        seen_ids.add(chunk_id)
        chunk_docs.append(enriched_chunk)
        embed_inputs.append(format_bge_document(enriched_chunk))
        chunk_ids.append(chunk_id)
        row_count = len({t["row"] for t in tsr_tokens if "row" in t})
        chunk_metas.append(
            {
                "doc_id": doc_id,
                "source": source_type,
                "course_id": course_id or -1,
                "document_name": pdf_path.stem,
                "source_pdf": pdf_path.name,
                "page": page,
                "section": section,
                "block_type": block_type,
                "chunk_index": chunk_index,
                "token_count": token_count,
                "is_table": block_type == "table",
                "row_count": row_count,
                "bbox": str(bbox) if bbox else "",
            }
        )

    if not chunk_docs:
        print("No valid chunk docs")
        return

    print("Embedding chunks...")

    chunk_embeddings = embed_texts(embed_inputs)

    chunk_collection.upsert(
        ids=chunk_ids,
        documents=chunk_docs,
        embeddings=chunk_embeddings,
        metadatas=chunk_metas,
    )

    print(f"Indexed document: {pdf_path.name}")

    print(f"Doc ID: {doc_id}")

    print(f"Chunks: {len(chunk_docs)}")


if __name__ == "__main__":
    pdf_dir = Path(r"DOCS")

    pdfs = list(pdf_dir.rglob("*.pdf"))

    print(f"Found {len(pdfs)} PDFs")

    for pdf_file in pdfs:
        result = process_pdf(str(pdf_file))

        preview_chunks(
            result,
            n=10,
        )

        save_jsonl(result, pdf_file.stem + ".jsonl")

        ingest_pdf(pdf_file)
