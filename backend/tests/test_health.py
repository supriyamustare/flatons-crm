from app.services import health as health_service


async def _up() -> bool:
    return True


async def _down() -> bool:
    return False


async def test_health_ok(client, monkeypatch):
    monkeypatch.setattr(health_service, "check_database", _up)
    monkeypatch.setattr(health_service, "check_redis", _up)

    resp = await client.get("/api/health")

    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "database": "ok", "redis": "ok"}


async def test_health_degraded_when_database_down(client, monkeypatch):
    monkeypatch.setattr(health_service, "check_database", _down)
    monkeypatch.setattr(health_service, "check_redis", _up)

    resp = await client.get("/api/health")

    assert resp.status_code == 503
    assert resp.json()["status"] == "degraded"
    assert resp.json()["database"] == "error"
