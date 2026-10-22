"""Celery application (worker + beat)."""

from celery import Celery

from app.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "flatons_crm",
    broker=settings.broker_url,
    backend=settings.redis_url,
    include=["app.tasks.system"],
)

celery_app.conf.update(
    timezone="Asia/Kolkata",
    enable_utc=True,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    result_expires=3600,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,
)

# Scheduled jobs are added here in later sprints (e.g. daily digest at 08:00 IST).
celery_app.conf.beat_schedule = {}
