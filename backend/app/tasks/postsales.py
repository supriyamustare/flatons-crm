"""Daily payment reminders, run by Celery beat at 09:00 India time."""

import asyncio
import logging
from datetime import UTC, datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.services.followups import run_reminders
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)
IST = timezone(timedelta(hours=5, minutes=30))


async def _run() -> dict:
    engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            counts = await run_reminders(db, datetime.now(UTC).astimezone(IST).date())
            await db.commit()
            return counts
    finally:
        await engine.dispose()


@celery_app.task(name="postsales.payment_reminders")
def payment_reminders() -> dict:
    counts = asyncio.run(_run())
    logger.info("Payment reminders: %s", counts)
    return counts
