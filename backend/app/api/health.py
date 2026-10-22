from fastapi import APIRouter, Response

from app.services import health as health_service

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(response: Response) -> dict[str, str]:
    """Liveness check: returns 200 when the database and Redis are reachable, else 503."""
    db_ok = await health_service.check_database()
    redis_ok = await health_service.check_redis()
    ok = db_ok and redis_ok
    if not ok:
        response.status_code = 503
    return {
        "status": "ok" if ok else "degraded",
        "database": "ok" if db_ok else "error",
        "redis": "ok" if redis_ok else "error",
    }
