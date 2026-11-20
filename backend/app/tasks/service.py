"""Ticket escalations, checked every 15 minutes by Celery beat."""

import asyncio
import logging

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.services.notifications import notify
from app.services.tickets import now, run_escalations
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


async def _run() -> dict:
    engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            counts = await run_escalations(db, now(), notify)
            await db.commit()
            return counts
    finally:
        await engine.dispose()


@celery_app.task(name="service.escalations")
def escalations() -> dict:
    counts = asyncio.run(_run())
    logger.info("Ticket escalations: %s", counts)
    return counts
