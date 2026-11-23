"""Customer message dispatcher, every 2 minutes."""

import asyncio
import logging

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.services.comms import dispatch
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


async def _run() -> dict:
    engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            counts = await dispatch(db)
            await db.commit()
            return counts
    finally:
        await engine.dispose()


@celery_app.task(name="comms.dispatch")
def run() -> dict:
    counts = asyncio.run(_run())
    if any(counts.values()):
        logger.info("Customer messages: %s", counts)
    return counts
