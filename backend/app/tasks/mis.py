"""Nightly MIS snapshot (23:30 IST)."""

import asyncio
import logging

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.services.mis import take_snapshot
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


async def _run() -> int:
    engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            n = await take_snapshot(db)
            await db.commit()
            return n
    finally:
        await engine.dispose()


@celery_app.task(name="mis.snapshot")
def snapshot() -> int:
    n = asyncio.run(_run())
    logger.info("MIS snapshots saved: %s", n)
    return n
