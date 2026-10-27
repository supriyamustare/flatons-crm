"""Facebook sends only a lead id.

This job fetches the details from the Graph API and files the lead."""

import asyncio
import logging

import httpx
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.core.crypto import decrypt
from app.models.integration import InboundEvent, InboundStatus
from app.services.inbound import ingest, parse_facebook_lead
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)
GRAPH = "https://graph.facebook.com/v21.0"


async def fetch_facebook_lead_data(leadgen_id: str, page_token: str) -> dict:
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(f"{GRAPH}/{leadgen_id}", params={"access_token": page_token})
        r.raise_for_status()
        return r.json()


async def process_facebook_event(event_id: int) -> str:
    engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            event = await db.get(InboundEvent, event_id)
            if event is None or event.status != InboundStatus.pending:
                return "skipped"
            integration = event.integration
            token = decrypt(integration.fb_page_token_enc or "")
            if not token:
                event.status, event.error = (
                    InboundStatus.failed,
                    "Facebook page token missing; re-enter it",
                )
                await db.commit()
                return event.status.value
            data = await fetch_facebook_lead_data(event.external_id or "", token)
            await ingest(
                db,
                integration,
                parse_facebook_lead(data),
                {**event.payload, "fetched": data},
                event=event,
            )
            integration.received_count -= 1  # already counted when the webhook arrived
            await db.commit()
            return event.status.value
    finally:
        await engine.dispose()


@celery_app.task(name="inbound.facebook_lead", bind=True, max_retries=3, default_retry_delay=60)
def facebook_lead(self, event_id: int) -> str:
    try:
        return asyncio.run(process_facebook_event(event_id))
    except httpx.HTTPError as exc:  # network or Facebook error: try again a little later
        logger.warning("Facebook lead fetch failed for event %s: %s", event_id, exc)
        raise self.retry(exc=exc) from exc
