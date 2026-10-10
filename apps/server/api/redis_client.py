"""
Shared async Redis client: refresh-token allowlist, login rate limiting, and
the permission-change pub/sub channel consumed by the sync server.
"""
import json
import logging
import os
import uuid

import redis.asyncio as redis

logger = logging.getLogger("synchronic.redis")

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
PERMISSION_CHANNEL = "synchronic:permissions"

_redis_client: redis.Redis | None = None


async def get_redis() -> redis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.from_url(REDIS_URL, decode_responses=True)
    return _redis_client


async def close_redis() -> None:
    global _redis_client
    if _redis_client is not None:
        await _redis_client.aclose()
        _redis_client = None


async def publish_permission_event(
    document_id: uuid.UUID, user_id: uuid.UUID | None = None, deleted: bool = False
) -> None:
    """Tell the sync server a document's access changed.

    user_id=None means "re-check everyone connected to this document" (e.g.
    link sharing toggled). Best-effort: the DB write has already committed, and
    the sync server also re-validates every connection on a timer, so a lost
    message only delays enforcement.
    """
    try:
        client = await get_redis()
        await client.publish(
            PERMISSION_CHANNEL,
            json.dumps(
                {
                    "document_id": str(document_id),
                    "user_id": str(user_id) if user_id else None,
                    "deleted": deleted,
                }
            ),
        )
    except Exception:
        logger.warning("Could not publish permission event for %s", document_id, exc_info=True)
