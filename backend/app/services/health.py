"""Dependency checks used by the health endpoint."""

import asyncio
import logging

from sqlalchemy import text

from app.core.db import engine
from app.core.redis import redis_client

logger = logging.getLogger(__name__)
TIMEOUT_SECONDS = 3


async def check_database() -> bool:
    async def _ping() -> None:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))

    try:
        await asyncio.wait_for(_ping(), TIMEOUT_SECONDS)
        return True
    except Exception:
        logger.exception("Database health check failed")
        return False


async def check_redis() -> bool:
    try:
        return bool(await asyncio.wait_for(redis_client.ping(), TIMEOUT_SECONDS))
    except Exception:
        logger.exception("Redis health check failed")
        return False
