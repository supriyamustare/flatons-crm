"""Celery application (worker + beat)."""

from celery import Celery
from celery.schedules import crontab

from app.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "flatons_crm",
    broker=settings.broker_url,
    backend=settings.redis_url,
    include=["app.tasks.system", "app.tasks.digest", "app.tasks.inventory", "app.tasks.inbound"],
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

# Times are India time (timezone above). Email delivery is added in Sprint 15.
celery_app.conf.beat_schedule = {
    "daily-follow-up-digest": {
        "task": "followups.daily_digest",
        "schedule": crontab(hour=8, minute=0),
    },
    "release-expired-unit-holds": {
        "task": "inventory.release_expired_holds",
        "schedule": crontab(minute="*/5"),
    },
}
