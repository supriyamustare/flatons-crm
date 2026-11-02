"""Daily follow-up digest, run by Celery beat at 08:00 India time."""

import asyncio
import logging

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.services.notifications import create_daily_digests
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


async def run_daily_digest() -> int:
    # Each Celery run gets its own event loop, so it uses its own short-lived connection
    # rather than the web app's pool.
    engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            created = await create_daily_digests(db)
            await db.commit()
            return created
    finally:
        await engine.dispose()


@celery_app.task(name="followups.daily_digest")
def daily_digest() -> int:
    created = asyncio.run(run_daily_digest())
    logger.info("Daily follow-up digest: %s notifications created", created)
    return created
