"""
infrastructure/redis_store.py
──────────────────────────────
Redis: conversation history, semantic answer cache, embedding cache, course meta.
"""

from __future__ import annotations

import hashlib
import json
import os

import redis

_REDIS_URL = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")
_pool: redis.ConnectionPool | None = None

HISTORY_TTL_SECONDS = int(os.getenv("REDIS_HISTORY_TTL", str(24 * 3600)))
CACHE_TTL_SECONDS = int(os.getenv("REDIS_CACHE_TTL", str(3600)))
EMBED_CACHE_TTL_SECONDS = int(os.getenv("REDIS_EMBED_CACHE_TTL", str(3600)))
COURSE_META_TTL_SECONDS = int(os.getenv("REDIS_COURSE_META_TTL", str(24 * 3600)))
MAX_HISTORY_TURNS = int(os.getenv("REDIS_MAX_HISTORY_TURNS", "40"))
MAX_CACHE_ENTRIES = int(os.getenv("REDIS_MAX_CACHE_ENTRIES", "200"))


def _get_redis() -> redis.Redis:
    global _pool
    if _pool is None:
        _pool = redis.ConnectionPool.from_url(
            _REDIS_URL,
            max_connections=10,
            decode_responses=True,
        )
    return redis.Redis(connection_pool=_pool)


def _history_key(user_id: int, room_id: int) -> str:
    return f"history:{user_id}:{room_id}"


def _semcache_key(course_id: int, user_id: int) -> str:
    """Per-user cache; global dashboard uses semcache:global:{user_id}."""
    uid = max(0, int(user_id))
    cid = int(course_id)
    if cid <= 0:
        return f"semcache:global:{uid}"
    return f"semcache:{cid}:{uid}"


def _legacy_semcache_key(course_id: int) -> str:
    """Pre-user scoping (course-only); still read for backward compatibility."""
    return f"semcache:{int(course_id)}"
    
def _shared_semcache_key(course_id: int) -> str:
    """Shared across all users of the same course — for common questions."""
    return f"semcache:shared:{int(course_id)}"

def _embed_cache_key(text: str) -> str:
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:32]
    return f"embedcache:{digest}"


def _course_meta_key(course_id: int) -> str:
    return f"coursemeta:{int(course_id)}"


# ── Conversation history ──────────────────────────────────────────────────────

def append_turn(user_id: int, room_id: int, role: str, content: str) -> None:
    r = _get_redis()
    key = _history_key(user_id, room_id)
    entry = json.dumps({"role": role, "content": content}, ensure_ascii=False)
    pipe = r.pipeline()
    pipe.rpush(key, entry)
    pipe.ltrim(key, -MAX_HISTORY_TURNS, -1)
    pipe.expire(key, HISTORY_TTL_SECONDS)
    pipe.execute()


def get_history(user_id: int, room_id: int) -> list[dict]:
    r = _get_redis()
    raw_list = r.lrange(_history_key(user_id, room_id), 0, -1)
    result: list[dict] = []
    for raw in raw_list:
        try:
            result.append(json.loads(raw))
        except json.JSONDecodeError:
            pass
    return result


def clear_history(user_id: int, room_id: int) -> int:
    return _get_redis().delete(_history_key(user_id, room_id))


def clear_all_history(user_id: int) -> int:
    r = _get_redis()
    deleted = 0
    cursor = 0
    while True:
        cursor, keys = r.scan(cursor, match=f"history:{user_id}:*", count=100)
        if keys:
            deleted += r.delete(*keys)
        if cursor == 0:
            break
    return deleted


def get_all_room_ids(user_id: int) -> list[int]:
    r = _get_redis()
    room_ids: list[int] = []
    cursor = 0
    while True:
        cursor, keys = r.scan(cursor, match=f"history:{user_id}:*", count=100)
        for key in keys:
            parts = str(key).split(":")
            if len(parts) == 3:
                try:
                    room_ids.append(int(parts[2]))
                except ValueError:
                    pass
        if cursor == 0:
            break
    return room_ids


# ── Semantic answer cache ───────────────────────────────────────────────────

def get_semantic_cache(course_id: int, user_id: int = 0) -> list[dict]:
    try:
        r = _get_redis()
        keys = [_semcache_key(course_id, user_id)]
        if int(course_id) > 0 and int(user_id) > 0:
            keys.append(_legacy_semcache_key(course_id))
        # Check shared course cache — benefits all users of the same course
        if int(course_id) > 0:
            keys.append(_shared_semcache_key(course_id))
        result: list[dict] = []
        seen: set[str] = set()
        for key in keys:
            for raw in r.lrange(key, 0, -1):
                if raw in seen:
                    continue
                seen.add(raw)
                try:
                    result.append(json.loads(raw))
                except json.JSONDecodeError:
                    pass
        return result
    except Exception:
        return []


def set_shared_semantic_cache(
    course_id: int,
    embedding: list[float],
    query: str,
    reply: str,
) -> None:
    """Store a high-confidence answer in the shared course cache (all users)."""
    try:
        r = _get_redis()
        key = _shared_semcache_key(course_id)
        entry = json.dumps(
            {"embedding": embedding, "reply": reply, "query": query},
            ensure_ascii=False,
        )
        pipe = r.pipeline()
        pipe.rpush(key, entry)
        pipe.ltrim(key, -MAX_CACHE_ENTRIES, -1)
        pipe.expire(key, CACHE_TTL_SECONDS)
        pipe.execute()
    except Exception as e:
        print(f"[SharedSemanticCache] Store failed (non-fatal): {e}")

def set_semantic_cache(
    course_id: int,
    user_id: int,
    embedding: list[float],
    query: str,
    reply: str,
) -> None:
    try:
        r = _get_redis()
        key = _semcache_key(course_id, user_id)
        entry = json.dumps(
            {"embedding": embedding, "reply": reply, "query": query},
            ensure_ascii=False,
        )
        pipe = r.pipeline()
        pipe.rpush(key, entry)
        pipe.ltrim(key, -MAX_CACHE_ENTRIES, -1)
        pipe.expire(key, CACHE_TTL_SECONDS)
        pipe.execute()
    except Exception as e:
        print(f"[SemanticCache] Store failed (non-fatal): {e}")


def clear_semantic_cache(course_id: int) -> int:
    r = _get_redis()
    deleted = 0
    cursor = 0
    pattern = f"semcache:{int(course_id)}:*"
    while True:
        cursor, keys = r.scan(cursor, match=pattern, count=100)
        if keys:
            deleted += r.delete(*keys)
        if cursor == 0:
            break
    deleted += r.delete(_legacy_semcache_key(course_id))
    deleted += r.delete(_shared_semcache_key(course_id))  # add this line
    return deleted

def clear_all_semantic_caches() -> int:
    r = _get_redis()
    deleted = 0
    cursor = 0
    while True:
        cursor, keys = r.scan(cursor, match="semcache:*", count=100)
        if keys:
            deleted += r.delete(*keys)
        if cursor == 0:
            break
    return deleted

SUMMARY_CACHE_TTL_SECONDS = int(os.getenv("REDIS_SUMMARY_CACHE_TTL", str(12 * 3600)))


def _summary_cache_key(course_id: int, language: str, style: str = "standard") -> str:
    return f"summary:{int(course_id)}:{language}:{style}"


def get_summary_cache(course_id: int, language: str = "id", style: str = "standard") -> str | None:
    try:
        raw = _get_redis().get(_summary_cache_key(course_id, language, style))
        return raw if raw else None
    except Exception:
        return None

def set_summary_cache(course_id: int, language: str, summary: str, style: str = "standard") -> None:
    try:
        _get_redis().setex(
            _summary_cache_key(course_id, language, style),
            SUMMARY_CACHE_TTL_SECONDS,
            summary,
        )
    except Exception as e:
        print(f"[SummaryCache] Store failed (non-fatal): {e}")

def clear_summary_cache(course_id: int) -> int:
    r = _get_redis()
    deleted = 0
    for lang in ("id", "en"):
        for style in ("brief", "standard", "detailed"):
            deleted += r.delete(_summary_cache_key(course_id, lang, style))
    return deleted

# ── Query embedding cache ─────────────────────────────────────────────────────

def get_embedding_cache(query_text: str) -> list[float] | None:
    try:
        raw = _get_redis().get(_embed_cache_key(query_text))
        if not raw:
            return None
        data = json.loads(raw)
        if isinstance(data, list):
            return [float(x) for x in data]
    except Exception:
        pass
    return None


def set_embedding_cache(query_text: str, embedding: list[float], ttl: int | None = None) -> None:
    try:
        ttl = int(ttl if ttl is not None else EMBED_CACHE_TTL_SECONDS)
        _get_redis().setex(
            _embed_cache_key(query_text),
            ttl,
            json.dumps(embedding),
        )
    except Exception as e:
        print(f"[EmbedCache] Store failed (non-fatal): {e}")


# ── Course metadata (name + timemodified) ─────────────────────────────────────

def get_course_meta(course_id: int) -> dict | None:
    try:
        raw = _get_redis().get(_course_meta_key(course_id))
        if not raw:
            return None
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def set_course_meta(course_id: int, fullname: str, timemodified: int) -> None:
    try:
        _get_redis().setex(
            _course_meta_key(course_id),
            COURSE_META_TTL_SECONDS,
            json.dumps(
                {"fullname": fullname, "timemodified": int(timemodified)},
                ensure_ascii=False,
            ),
        )
    except Exception as e:
        print(f"[CourseMeta] Store failed (non-fatal): {e}")


def redis_health_check() -> dict:
    try:
        _get_redis().ping()
        return {"redis": "ok"}
    except Exception as e:
        return {"redis": "error", "detail": str(e)}
