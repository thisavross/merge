"""
scripts/migrate_legacy_collections.py
──────────────────────────────────────
ONE-TIME migration script.

Run this ONCE to:
  1. Copy all entries from legacy per-course collections (course_2, course_3, course_4, ...)
     into the canonical moodle_chat and moodle_coursecontent collections.
  2. Copy entries from the old moodle_quiz collection into moodle_coursecontent
     (only if moodle_coursecontent is a different name in your .env).
  3. Delete the legacy collections.

After this script completes your chroma_db/ should have three collections
(config defaults: moodle_chat, moodle_course, sinarmas_knowledge).
Prefer scripts/rename_to_moodle_course.py for moodle_quiz → moodle_course rename.

HOW TO RUN:
    cd local/chatbot/rag_service
    source .venv/bin/activate
    python scripts/migrate_legacy_collections.py

    # Add --dry-run to preview what would be moved without writing anything:
    python scripts/migrate_legacy_collections.py --dry-run

    # To also delete legacy collections after copying:
    python scripts/migrate_legacy_collections.py --delete-legacy
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import chromadb
from config import Settings, settings
# Make sure the service modules are importable
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


KEEP_COLLECTIONS = {
    "moodle_chat",
    "moodle_course",
    "sinarmas_knowledge"
}

# Pattern for old per-course collections.
LEGACY_COURSE_PATTERN = re.compile(r"^course_\d+$")

# Old learning-only collection name (before the rename).
LEGACY_QUIZ_COLLECTION = "moodle_quiz"


def _is_legacy(name: str, canonical_content: str) -> bool:
    """True when a collection should be migrated or deleted."""
    if name in KEEP_COLLECTIONS:
        return False
    if name == canonical_content:
        return False  # Already canonical
    if LEGACY_COURSE_PATTERN.match(name):
        return True
    if name == LEGACY_QUIZ_COLLECTION and canonical_content != LEGACY_QUIZ_COLLECTION:
        return True
    return False


def _copy_collection(
    src: chromadb.Collection,
    dst_chat: chromadb.Collection,
    dst_content: chromadb.Collection,
    dry_run: bool,
) -> dict[str, int]:
    """Copy entries from a legacy collection into the canonical collections.

    Routing logic:
      - chunk_type == "learning"  →  moodle_coursecontent
      - everything else           →  moodle_chat
    """
    total = src.count()
    if total == 0:
        print(f"  [SKIP] {src.name!r} is empty.")
        return {"chat": 0, "content": 0}

    result = src.get(include=["documents", "embeddings", "metadatas"])
    ids = result.get("ids") or []
    docs = result.get("documents") or []
    embs = result.get("embeddings") or []
    metas = result.get("metadatas") or []

    chat_ids, chat_docs, chat_embs, chat_metas = [], [], [], []
    content_ids, content_docs, content_embs, content_metas = [], [], [], []

    for i, (rid, doc, emb, meta) in enumerate(zip(ids, docs, embs, metas)):
        if not doc or not emb:
            continue
        # Prefix the ID to avoid collisions with existing entries.
        new_id = f"migrated_{src.name}_{rid}"
        chunk_type = (meta or {}).get("chunk_type", "general")
        if chunk_type == "learning":
            content_ids.append(new_id)
            content_docs.append(doc)
            content_embs.append(emb)
            content_metas.append(meta or {})
        else:
            chat_ids.append(new_id)
            chat_docs.append(doc)
            chat_embs.append(emb)
            chat_metas.append(meta or {})

    print(
        f"  {src.name!r}: {len(chat_ids)} → moodle_chat, "
        f"{len(content_ids)} → moodle_coursecontent"
        + (" (DRY RUN)" if dry_run else "")
    )

    if not dry_run:
        BATCH = 100
        for start in range(0, len(chat_ids), BATCH):
            dst_chat.add(
                ids=chat_ids[start:start + BATCH],
                documents=chat_docs[start:start + BATCH],
                embeddings=chat_embs[start:start + BATCH],
                metadatas=chat_metas[start:start + BATCH],
            )
        for start in range(0, len(content_ids), BATCH):
            dst_content.add(
                ids=content_ids[start:start + BATCH],
                documents=content_docs[start:start + BATCH],
                embeddings=content_embs[start:start + BATCH],
                metadatas=content_metas[start:start + BATCH],
            )

    return {"chat": len(chat_ids), "content": len(content_ids)}


def migrate(dry_run: bool = False, delete_legacy: bool = False) -> None:

    client = chromadb.HttpClient(
        host=Settings.chroma_host,
        port=Settings.chroma_port,
    )

    # Resolve canonical content collection name from .env / config.
    try:
        from config import settings
        canonical_content = settings.moodle_coursecontent_collection
        canonical_chat = settings.moodle_chat_collection
    except Exception:
        canonical_content = "moodle_course"
        canonical_chat = "moodle_chat"

    print(f"Canonical collections: chat={canonical_chat!r} content={canonical_content!r}")
    print(f"Mode: {'DRY RUN' if dry_run else 'LIVE'}")
    print()

    all_names = [c.name for c in client.list_collections()]
    print(f"Collections on disk ({len(all_names)}): {all_names}")
    print()

    legacy = [n for n in all_names if _is_legacy(n, canonical_content)]
    if not legacy:
        print("Nothing to migrate. All collections are already canonical.")
        return

    print(f"Legacy collections to migrate: {legacy}")
    print()

    dst_chat = client.get_or_create_collection(
        canonical_chat, metadata={"hnsw:space": "cosine"}
    )
    dst_content = client.get_or_create_collection(
        canonical_content, metadata={"hnsw:space": "cosine"}
    )

    total_chat = 0
    total_content = 0

    for name in legacy:
        src = client.get_collection(name)
        counts = _copy_collection(src, dst_chat, dst_content, dry_run)
        total_chat += counts["chat"]
        total_content += counts["content"]

    print()
    print(
        f"Migration summary: {total_chat} chat chunks, "
        f"{total_content} content chunks"
        + (" (would be written)" if dry_run else " written")
    )

    if delete_legacy and not dry_run:
        print()
        for name in legacy:
            print(f"  Deleting {name!r}...")
            client.delete_collection(name)
        print("Legacy collections deleted.")
    elif delete_legacy and dry_run:
        print(f"\nWould delete: {legacy} (skipped in dry-run)")
    else:
        print(
            f"\nLegacy collections NOT deleted. "
            f"Re-run with --delete-legacy to remove them."
        )

    print("\nDone.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Migrate legacy ChromaDB collections.")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Preview what would be migrated without writing anything."
    )
    parser.add_argument(
        "--delete-legacy", action="store_true",
        help="Delete legacy collections after copying their entries."
    )
    args = parser.parse_args()
    migrate(dry_run=args.dry_run, delete_legacy=args.delete_legacy)