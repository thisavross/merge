"""
inspect_chroma.py
-----------------
View ChromaDB collections: moodle_chat, moodle_course, sinarmas_knowledge.

How to run:
    cd local/chatbot/rag_service
    source .venv/bin/activate
    python inspect_chroma.py
"""

from __future__ import annotations

from pathlib import Path
from config import Settings
import chromadb

CHROMA_PATH = Path(__file__).resolve().parents[1] / "chroma_db"
COLLECTIONS = ("moodle_chat", "moodle_course", "sinarmas_knowledge")
SHOW_FIRST_N = 20
SEARCH_QUERY = "summarize course"
SHOW_COLLECTION = "moodle_course"  # collection to preview
SHOW_COURSE_ID = 4  # filter course tertentu, 0 = semua
SHOW_FIRST_N = 10  # berapa chunk yang ditampilkan
SHOW_FULL_CONTENT = True  # True = tampilkan full teks chunk
SEARCH_QUERY = ""  # kosongkan dulu
SEARCH_COURSE_ID = 0


def _preview_collection(client, name: str) -> None:
    try:
        col = client.get_collection(name)
    except Exception:
        print(f"  '{name}': (not created yet)")
        return

    total = col.count()
    print(f"  '{name}': {total} entries")

    if total == 0:
        return

    sample = col.get(limit=min(total, 500), include=["metadatas"])
    course_ids: set[int] = set()
    sources: set[str] = set()
    chunk_types: set[str] = set()
    for meta in sample.get("metadatas") or []:
        if not meta:
            continue
        if meta.get("course_id") is not None:
            course_ids.add(int(meta["course_id"]))
        if meta.get("source"):
            sources.add(str(meta["source"]))
        if meta.get("chunk_type"):
            chunk_types.add(str(meta["chunk_type"]))

    if course_ids:
        print(f"    course_ids: {sorted(course_ids)}")
    if chunk_types:
        print(f"    chunk_types: {sorted(chunk_types)}")
    if sources and name == "sinarmas_knowledge":
        print(f"    sources: {len(sources)} PDF(s)")

    preview = col.get(limit=SHOW_FIRST_N, include=["documents", "metadatas"])
    for i, (doc, meta) in enumerate(
        zip(preview.get("documents", []), preview.get("metadatas", []))
    ):
        cid = (meta or {}).get("course_id", "-")
        ctype = (meta or {}).get("chunk_type", "-")
        text = ((doc or "")[:160]).replace("\n", " ")
        print(f"    [{i}] course_id={cid} chunk_type={ctype}")
        print(f"         {text}...")


def main() -> None:

    client = chromadb.HttpClient(
        host=Settings.chroma_host,
        port=Settings.chroma_port,
    )

    print(f"Chroma server: {Settings.chroma_host}:{Settings.chroma_port}\n")

    print("Collections:")
    for name in client.list_collections():
        print(f"  - {name.name}")
    print()

    for coll in COLLECTIONS:
        print(coll + ":")
        _preview_collection(client, coll)
        print()

    # Tambah setelah semua print, sebelum if SEARCH_QUERY:
    # from config import settings
    # from rag_engine import _delete_course_chunks, _index_course
    # print("\n[RE-INDEX] Deleting and re-indexing course_id=4...")
    # _delete_course_chunks(4, settings)
    # _index_course(4, settings)
    # print("[RE-INDEX] Done.")
    if SEARCH_QUERY.strip():
        from config import settings
        from ollama_http import get_embedding

        vec = get_embedding(settings, SEARCH_QUERY)
        where = {"course_id": SEARCH_COURSE_ID} if SEARCH_COURSE_ID > 0 else None
        for coll_name in ("moodle_chat", "moodle_course"):
            try:
                col = client.get_collection(coll_name)
                if col.count() == 0:
                    continue
                results = col.query(
                    query_embeddings=[vec],
                    n_results=3,
                    where=where,
                    include=["documents", "metadatas", "distances"],
                )
                print(f"Search in '{coll_name}' (where={where}):")
                for doc, meta, dist in zip(
                    results.get("documents", [[]])[0],
                    results.get("metadatas", [[]])[0],
                    results.get("distances", [[]])[0],
                ):
                    sim = 1 - float(dist)
                    print(f"  sim={sim:.4f} meta={meta}")
                    print(f"  {(doc or '')[:200]}...")
                print()
            except Exception as e:
                print(f"  Search failed for {coll_name}: {e}")


if __name__ == "__main__":
    main()
