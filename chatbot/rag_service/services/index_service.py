"""Course and Sinarmas index maintenance."""

from __future__ import annotations

from config import settings
from retrieval.chroma_store import (
    ensure_course_indexed,
    reset_chroma_client,
    schedule_course_reindex,
)
from infrastructure.redis_store import clear_summary_cache


def run_sinarmas_rebuild() -> None:
    """Rebuild Sinarmas Chroma collection and reset the shared client."""
    from scripts import build_sinarmas_index

    build_sinarmas_index.build()
    reset_chroma_client()


def warm_course_index(course_id: int, *, sync: bool = True) -> str:
    """Index one Moodle course (blocking when sync=True)."""
    col, name = ensure_course_indexed(
        int(course_id),
        settings,
        force_sync=sync,
    )
    clear_summary_cache(int(course_id))  

    _ = col
    return name


def queue_course_reindex(course_id: int) -> bool:
    """Schedule background re-index for one course."""
    return schedule_course_reindex(int(course_id), settings)
