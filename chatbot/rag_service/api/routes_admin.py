"""Health, rebuild-index, and quiz PDF routes."""

from __future__ import annotations

import asyncio
import traceback
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import Response

from api.models import CourseReindexRequest, IngestPdfRequest, QuizPdfRequest
from infrastructure.redis_store import clear_all_semantic_caches, clear_semantic_cache, redis_health_check
from services.index_service import ingest_uploaded_pdf, queue_course_reindex, run_sinarmas_rebuild, warm_course_index
from services.quiz_service import quiz_from_json, quiz_to_pdf

router = APIRouter()
_executor = ThreadPoolExecutor(max_workers=1)
_rebuild_in_progress = False


def _run_rebuild() -> None:
    global _rebuild_in_progress
    try:
        print("[Rebuild] Starting...")
        run_sinarmas_rebuild()
        cleared = clear_all_semantic_caches()
        print(f"[Rebuild] Cleared {cleared} semantic cache key(s).")
        print("[Rebuild] Done.")
    except Exception as e:
        print(f"[Rebuild] ERROR: {e}")
        traceback.print_exc()
    finally:
        _rebuild_in_progress = False


@router.post("/quiz/pdf")
def download_quiz_pdf(body: QuizPdfRequest) -> Response:
    questions = quiz_from_json(body.quiz_json)
    if not questions:
        raise HTTPException(status_code=400, detail="No quiz questions provided")

    try:
        pdf_bytes = quiz_to_pdf(questions, body.coursename, body.language)
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))

    filename = f"quiz_{body.coursename.replace(' ', '_')[:30]}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/rebuild-index")
async def rebuild_index(request: Request, background_tasks: BackgroundTasks):
    global _rebuild_in_progress
    try:
        body = await request.json()
        records = body.get("Records", [])
        key = records[0].get("s3", {}).get("object", {}).get("key", "?") if records else "?"
        print(f"[Rebuild] MinIO event — object: {key}")
    except Exception:
        print("[Rebuild] Received webhook")

    if _rebuild_in_progress:
        return {"status": "already in progress"}
    _rebuild_in_progress = True
    loop = asyncio.get_event_loop()
    loop.run_in_executor(_executor, _run_rebuild)
    return {"status": "rebuild started"}


@router.post("/admin/reindex/course")
def reindex_course(
    body: CourseReindexRequest,
    background_tasks: BackgroundTasks,
) -> dict:
    """Pre-warm or refresh vectors for one Moodle course (called from Moodle on course update)."""
    cid = int(body.course_id)
    if cid <= 1:
        raise HTTPException(status_code=400, detail="course_id must be > 1")

    if body.sync:
        try:
            name = warm_course_index(cid, sync=True)
            cleared = clear_semantic_cache(cid)
            return {"status": "ok", "course_id": cid, "coursename": name, "cache_keys_cleared": cleared}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e)) from e

    scheduled = queue_course_reindex(cid)
    return {"status": "scheduled" if scheduled else "already_running", "course_id": cid}


@router.post("/admin/ingest/pdf")
def ingest_pdf(body: IngestPdfRequest) -> dict:
    """Index one PDF via local/ocr/extract.py into moodle_chat + moodle_course."""
    pdf_path = body.pdf_path.strip()
    if not pdf_path:
        raise HTTPException(status_code=400, detail="pdf_path is required")

    try:
        result = ingest_uploaded_pdf(
            pdf_path,
            course_id=body.course_id,
            source_type=body.source_type,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e

    cache_keys_cleared = 0
    if body.course_id is not None and int(body.course_id) > 1:
        cache_keys_cleared = clear_semantic_cache(int(body.course_id))

    return {
        "status": result.get("status", "ok"),
        "course_id": body.course_id,
        "cache_keys_cleared": cache_keys_cleared,
        **result,
    }


@router.get("/health")
def health() -> dict:
    redis_status = redis_health_check()
    return {
        "status": "ok",
        "rebuild_in_progress": _rebuild_in_progress,
        **{f"redis_{k}" if k != "redis" else k: v for k, v in redis_status.items()},
    }
