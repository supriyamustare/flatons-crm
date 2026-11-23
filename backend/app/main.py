"""Flatons CRM API entry point."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import (
    agreements,
    appointments,
    auth,
    bookings,
    calls,
    cancellations,
    case_documents,
    channel_partners,
    cost_sheets,
    dashboard,
    demands,
    floor_plans,
    followups,
    health,
    inbound,
    integrations,
    inventory,
    leads,
    ledger,
    loans,
    marketing,
    milestones,
    notifications,
    payments,
    pipeline,
    possession,
    postsales,
    project_legal,
    project_updates,
    projects,
    reports,
    tasks,
    tickets,
    users,
    visits,
)
from app.core.config import get_settings
from app.core.db import engine
from app.core.redis import redis_client

settings = get_settings()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
    await engine.dispose()
    await redis_client.aclose()


app = FastAPI(
    title="Flatons CRM API",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url=None,
    openapi_url="/api/openapi.json",
)

if settings.cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.include_router(health.router, prefix="/api")
app.include_router(auth.router, prefix="/api")
app.include_router(users.router, prefix="/api")
app.include_router(projects.router, prefix="/api")
app.include_router(inventory.router, prefix="/api")
app.include_router(tasks.router, prefix="/api")
app.include_router(notifications.router, prefix="/api")
app.include_router(calls.router, prefix="/api")
app.include_router(visits.router, prefix="/api")
app.include_router(dashboard.router, prefix="/api")
app.include_router(pipeline.router, prefix="/api")
app.include_router(marketing.router, prefix="/api")
app.include_router(reports.router, prefix="/api")
app.include_router(integrations.router, prefix="/api")
app.include_router(inbound.router, prefix="/api")
app.include_router(bookings.router, prefix="/api")
app.include_router(cost_sheets.router, prefix="/api")
app.include_router(channel_partners.router, prefix="/api")
app.include_router(floor_plans.router, prefix="/api")
app.include_router(project_legal.router, prefix="/api")
app.include_router(postsales.router, prefix="/api")
app.include_router(ledger.router, prefix="/api")
app.include_router(payments.router, prefix="/api")
app.include_router(milestones.router, prefix="/api")
app.include_router(demands.router, prefix="/api")
app.include_router(followups.router, prefix="/api")
app.include_router(case_documents.router, prefix="/api")
app.include_router(agreements.router, prefix="/api")
app.include_router(loans.router, prefix="/api")
app.include_router(appointments.router, prefix="/api")
app.include_router(project_updates.router, prefix="/api")
app.include_router(tickets.router, prefix="/api")
app.include_router(possession.router, prefix="/api")
app.include_router(possession.evidence_router, prefix="/api")
app.include_router(cancellations.router, prefix="/api")
app.include_router(leads.router, prefix="/api")
