"""Releases unit holds whose time is up. Runs every 5 minutes via Celery beat."""

import asyncio
import logging

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.services.inventory import release_expired_holds
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


async def run_release_expired_holds() -> int:
    engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            released = await release_expired_holds(db)
            await db.commit()
            return released
    finally:
        await engine.dispose()


@celery_app.task(name="inventory.release_expired_holds")
def release_expired() -> int:
    released = asyncio.run(run_release_expired_holds())
    if released:
        logger.info("Released %s expired unit hold(s)", released)
    return released
