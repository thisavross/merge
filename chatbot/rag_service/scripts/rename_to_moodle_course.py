"""
One-time: rename moodle_quiz → moodle_course, keep 3 collections, delete the rest.

Keeps:  moodle_chat, moodle_course, sinarmas_knowledge
Drops:  moodle_quiz, moodle_coursecontent, course_*, and any other names

Run:
    cd local/chatbot/rag_service
    source .venv/bin/activate
    python scripts/rename_to_moodle_course.py --dry-run
    python scripts/rename_to_moodle_course.py
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from config import Settings

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import chromadb

CHROMA_PATH = Path(__file__).resolve().parents[1] / "chroma_db"
KEEP = frozenset({"moodle_chat", "moodle_course", "sinarmas_knowledge"})
SOURCE_LEARNING = "moodle_quiz"
TARGET_LEARNING = "moodle_course"
COSINE_META = {"hnsw:space": "cosine"}
BATCH = 100


def _copy_all(src: chromadb.Collection, dst: chromadb.Collection, dry_run: bool) -> int:
    total = src.count()
    if total == 0:
        return 0
    if dry_run:
        print(f"  Would copy {total} entries from {src.name!r} → {dst.name!r}")
        return total

    data = src.get(include=["embeddings", "documents", "metadatas"])
    ids = data.get("ids") or []
    if not ids:
        return 0

    n = 0
    for i in range(0, len(ids), BATCH):
        sl = slice(i, i + BATCH)
        dst.upsert(
            ids=ids[sl],
            embeddings=data["embeddings"][sl],
            documents=data["documents"][sl],
            metadatas=data["metadatas"][sl],
        )
        n += len(ids[sl])
    return n


def run(*, dry_run: bool) -> None:
    if not CHROMA_PATH.exists():
        print("[ERROR] chroma_db/ not found.")
        sys.exit(1)

    client = chromadb.HttpClient(
        host=Settings.chroma_host,
        port=Settings.chroma_port,
    )
    names = {c.name for c in client.list_collections()}
    print(f"Before ({len(names)}): {sorted(names)}")
    print(f"Mode: {'DRY RUN' if dry_run else 'LIVE'}\n")

    # ── 1. moodle_quiz → moodle_course ───────────────────────────────────────
    if SOURCE_LEARNING in names:
        if not dry_run:
            dst = client.get_or_create_collection(TARGET_LEARNING, metadata=COSINE_META)
            src = client.get_collection(SOURCE_LEARNING)
            copied = _copy_all(src, dst, dry_run=False)
            print(
                f"[OK] Copied {copied} entries: {SOURCE_LEARNING!r} → {TARGET_LEARNING!r}"
            )
        else:
            src = client.get_collection(SOURCE_LEARNING)
            _copy_all(
                src,
                client.get_or_create_collection(TARGET_LEARNING, metadata=COSINE_META),
                dry_run=True,
            )
    elif TARGET_LEARNING in names:
        print(
            f"[OK] {TARGET_LEARNING!r} already exists (no {SOURCE_LEARNING!r} to copy)."
        )
    else:
        print(
            f"[WARN] Neither {SOURCE_LEARNING!r} nor {TARGET_LEARNING!r} found; learning collection empty until re-index."
        )

    # ── 2. Delete everything not in KEEP ─────────────────────────────────────
    to_delete = sorted(names - KEEP)
    # After copy, moodle_quiz and moodle_coursecontent should be deleted
    if TARGET_LEARNING in to_delete:
        to_delete.remove(TARGET_LEARNING)

    if not to_delete:
        print("\nNo extra collections to delete.")
    else:
        print(f"\nCollections to delete ({len(to_delete)}): {to_delete}")
        for name in to_delete:
            if dry_run:
                print(
                    f"  Would delete {name!r} ({client.get_collection(name).count()} entries)"
                )
            else:
                client.delete_collection(name)
                print(f"  Deleted {name!r}")

    remaining = sorted(c.name for c in client.list_collections())
    print(f"\nAfter ({len(remaining)}): {remaining}")
    if set(remaining) != KEEP:
        extra = set(remaining) - KEEP
        missing = KEEP - set(remaining)
        if extra:
            print(f"[WARN] Unexpected collections still present: {extra}")
        if missing:
            print(f"[WARN] Missing canonical collections: {missing}")
    else:
        print(
            "[DONE] Exactly 3 collections: moodle_chat, moodle_course, sinarmas_knowledge"
        )


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true", help="Preview only")
    args = p.parse_args()
    run(dry_run=args.dry_run)
