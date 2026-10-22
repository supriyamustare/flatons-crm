from app.tasks.celery_app import celery_app


@celery_app.task(name="system.ping")
def ping() -> str:
    """Trivial task used to confirm the worker is processing jobs."""
    return "pong"
