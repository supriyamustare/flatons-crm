from sqlalchemy import select

from app.models import AuditLog, Role
from tests.conftest import TEST_PASSWORD


async def test_login_sets_httponly_cookies(client, make_user):
    user = await make_user(Role.executive)

    resp = await client.post(
        "/api/auth/login", json={"email": user.email, "password": TEST_PASSWORD}
    )

    assert resp.status_code == 200
    assert resp.json()["email"] == user.email
    assert "hashed_password" not in resp.json()
    cookies = resp.headers.get_list("set-cookie")
    access = next(c for c in cookies if c.startswith("access_token="))
    refresh = next(c for c in cookies if c.startswith("refresh_token="))
    assert "HttpOnly" in access and "Path=/api" in access
    assert "HttpOnly" in refresh and "Path=/api/auth" in refresh


async def test_login_email_is_case_insensitive(client, make_user):
    await make_user(email="priya@flatons.com")  # the API always stores emails lower-case
    resp = await client.post(
        "/api/auth/login", json={"email": "PRIYA@Flatons.com", "password": TEST_PASSWORD}
    )
    assert resp.status_code == 200
    assert resp.json()["email"] == "priya@flatons.com"


async def test_wrong_password_is_rejected_and_audited(client, make_user, db):
    user = await make_user()

    resp = await client.post("/api/auth/login", json={"email": user.email, "password": "nope-nope"})

    assert resp.status_code == 401
    assert resp.json()["detail"] == "Incorrect email or password"
    entry = await db.scalar(select(AuditLog).where(AuditLog.action == "auth.login_failed"))
    assert entry.details["reason"] == "bad_password"


async def test_unknown_email_gets_same_message(client):
    resp = await client.post(
        "/api/auth/login", json={"email": "ghost@flatons.com", "password": TEST_PASSWORD}
    )
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Incorrect email or password"


async def test_inactive_user_cannot_log_in(client, make_user):
    user = await make_user(is_active=False)
    resp = await client.post(
        "/api/auth/login", json={"email": user.email, "password": TEST_PASSWORD}
    )
    assert resp.status_code == 401


async def test_me_requires_login(client):
    assert (await client.get("/api/users/me")).status_code == 401


async def test_me_returns_profile(login_as):
    c, user = await login_as(Role.manager)
    resp = await c.get("/api/users/me")
    assert resp.status_code == 200
    assert resp.json()["role"] == "manager"
    assert resp.json()["id"] == user.id


async def test_refresh_restores_session_after_access_cookie_is_gone(login_as):
    c, _ = await login_as()
    c.cookies.delete("access_token")
    assert (await c.get("/api/users/me")).status_code == 401

    assert (await c.post("/api/auth/refresh")).status_code == 200
    assert (await c.get("/api/users/me")).status_code == 200


async def test_refresh_token_cannot_be_used_as_access_token(client, login_as):
    c, _ = await login_as()
    refresh_value = c.cookies.get("refresh_token")
    client.cookies.set("access_token", refresh_value)
    assert (await client.get("/api/users/me")).status_code == 401


async def test_tampered_token_is_rejected(client):
    client.cookies.set("access_token", "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.forged")
    assert (await client.get("/api/users/me")).status_code == 401


async def test_logout_clears_session(login_as):
    c, _ = await login_as()
    assert (await c.post("/api/auth/logout")).status_code == 204
    assert (await c.get("/api/users/me")).status_code == 401
    assert (await c.post("/api/auth/refresh")).status_code == 401


async def test_password_change_signs_out_other_devices(login_as, client):
    phone, user = await login_as()
    laptop_login = await client.post(
        "/api/auth/login", json={"email": user.email, "password": TEST_PASSWORD}
    )
    assert laptop_login.status_code == 200

    resp = await phone.post(
        "/api/users/me/password",
        json={"current_password": TEST_PASSWORD, "new_password": "brand-new-pass-1"},
    )

    assert resp.status_code == 204
    assert (await phone.get("/api/users/me")).status_code == 200  # this device stays in
    assert (await client.get("/api/users/me")).status_code == 401  # other device signed out
    relog = await client.post(
        "/api/auth/login", json={"email": user.email, "password": "brand-new-pass-1"}
    )
    assert relog.status_code == 200


async def test_password_change_requires_current_password(login_as):
    c, _ = await login_as()
    resp = await c.post(
        "/api/users/me/password",
        json={"current_password": "wrong-one", "new_password": "brand-new-pass-1"},
    )
    assert resp.status_code == 400
