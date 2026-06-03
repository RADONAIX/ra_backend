"""Redis client (cache + lightweight pub/sub).

A single async client is shared process-wide. Used for caching expensive
ClickHouse aggregations and as a seam for future event publishing.
"""

from __future__ import annotations

import json
from typing import Any

import redis.asyncio as aioredis

from app.core.config import settings

_redis: aioredis.Redis | None = None


def get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
        )
    return _redis


async def close_redis() -> None:
    global _redis
    if _redis is not None:
        await _redis.aclose()
        _redis = None


async def cache_get_json(key: str) -> Any | None:
    raw = await get_redis().get(key)
    return json.loads(raw) if raw else None


async def cache_set_json(key: str, value: Any, ttl_seconds: int = 30) -> None:
    await get_redis().set(key, json.dumps(value, default=str), ex=ttl_seconds)
