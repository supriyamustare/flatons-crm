import pytest
from sqlalchemy import select

from app.models import AuditLog, Role, User
from tests.conftest import TEST_PASSWORD

NEW_USER = {
    "email": "Ravi.Exec@Flatons.com",
    "full_name": "Ravi Kumar",
    "role": "executive",
    "password": "welcome-ravi-1",
}


@pytest.mark.parametrize(
    ("role", "expected"),
    [(Role.admin, 201), (Role.manager, 403), (Role.executive, 403), (Role.docs, 403)],
)
async def test_only_admin_can_create_users(login_as, role, expected):
    c, _ = await login_as(role)
    resp = await c.post("/api/users", json=NEW_USER)
    assert resp.status_code == expected


@pytest.mark.parametrize("role", [Role.manager, Role.executive, Role.docs])
async def test_non_admins_cannot_list_or_edit_users(login_as, make_user, role):
    c, _ = await login_as(role)
    other = await make_user()
    assert (await c.get("/api/users")).status_code == 403
    assert (await c.patch(f"/api/users/{other.id}", json={"role": "admin"})).status_code == 403
    assert (await c.delete(f"/api/users/{other.id}")).status_code == 403


async def test_user_endpoints_require_login(client):
    assert (await client.get("/api/users")).status_code == 401
    assert (await client.post("/api/users", json=NEW_USER)).status_code == 401


async def test_admin_creates_executive_who_can_then_log_in(login_as, client, db):
    """Sprint 1 'done when': admin creates an executive, and the executive can log in."""
    admin_client, admin = await login_as(Role.admin)

    resp = await admin_client.post("/api/users", json=NEW_USER)

    assert resp.status_code == 201
    body = resp.json()
    assert body["email"] == "ravi.exec@flatons.com"  # stored lower-case
    assert body["role"] == "executive"
    assert "password" not in body and "hashed_password" not in body

    login = await client.post(
        "/api/auth/login", json={"email": NEW_USER["email"], "password": NEW_USER["password"]}
    )
    assert login.status_code == 200
    assert login.json()["role"] == "executive"

    entry = await db.scalar(select(AuditLog).where(AuditLog.action == "user.create"))
    assert entry.actor_id == admin.id
    assert entry.entity_id == str(body["id"])
    assert entry.details == {"email": "ravi.exec@flatons.com", "role": "executive"}


async def test_duplicate_email_is_rejected(login_as, make_user):
    c, _ = await login_as(Role.admin)
    await make_user(email="ravi.exec@flatons.com")
    resp = await c.post("/api/users", json=NEW_USER)
    assert resp.status_code == 409


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("password", "short"),
        ("full_name", "<script>alert(1)</script>"),
        ("full_name", "   "),
        ("email", "not-an-email"),
        ("role", "superuser"),
    ],
)
async def test_invalid_user_data_is_rejected(login_as, field, value):
    c, _ = await login_as(Role.admin)
    resp = await c.post("/api/users", json={**NEW_USER, field: value})
    assert resp.status_code == 422


async def test_admin_lists_users(login_as, make_user):
    c, _ = await login_as(Role.admin)
    await make_user(Role.docs)
    resp = await c.get("/api/users")
    assert resp.status_code == 200
    assert {u["role"] for u in resp.json()} == {"admin", "docs"}


async def test_role_change_is_audited_with_before_and_after(login_as, make_user, db):
    c, admin = await login_as(Role.admin)
    target = await make_user(Role.executive)

    resp = await c.patch(f"/api/users/{target.id}", json={"role": "manager"})

    assert resp.status_code == 200
    assert resp.json()["role"] == "manager"
    entry = await db.scalar(select(AuditLog).where(AuditLog.action == "user.update"))
    assert entry.actor_id == admin.id
    assert entry.details == {"changes": {"role": {"from": "executive", "to": "manager"}}}


async def test_role_change_takes_effect_immediately(login_as):
    admin_client, _ = await login_as(Role.admin)
    exec_client, executive = await login_as(Role.executive)
    assert (await exec_client.get("/api/users")).status_code == 403

    await admin_client.patch(f"/api/users/{executive.id}", json={"role": "admin"})

    assert (await exec_client.get("/api/users")).status_code == 200


async def test_deactivation_signs_user_out_and_blocks_login(login_as, client, db):
    admin_client, admin = await login_as(Role.admin)
    exec_client, executive = await login_as(Role.executive)

    resp = await admin_client.delete(f"/api/users/{executive.id}")

    assert resp.status_code == 204
    assert (await exec_client.get("/api/users/me")).status_code == 401
    assert (await exec_client.post("/api/auth/refresh")).status_code == 401
    login = await client.post(
        "/api/auth/login", json={"email": executive.email, "password": TEST_PASSWORD}
    )
    assert login.status_code == 401
    entry = await db.scalar(select(AuditLog).where(AuditLog.action == "user.deactivate"))
    assert entry.actor_id == admin.id
    # The row is kept (soft delete), just marked inactive
    is_active = await db.scalar(select(User.is_active).where(User.id == executive.id))
    assert is_active is False


async def test_admin_can_reactivate_user(login_as, make_user, client):
    c, _ = await login_as(Role.admin)
    user = await make_user(is_active=False)

    resp = await c.patch(f"/api/users/{user.id}", json={"is_active": True})

    assert resp.status_code == 200
    login = await client.post(
        "/api/auth/login", json={"email": user.email, "password": TEST_PASSWORD}
    )
    assert login.status_code == 200


async def test_admin_password_reset_signs_user_out(login_as):
    admin_client, _ = await login_as(Role.admin)
    exec_client, executive = await login_as(Role.executive)

    resp = await admin_client.patch(
        f"/api/users/{executive.id}", json={"password": "reset-by-admin-1"}
    )

    assert resp.status_code == 200
    assert (await exec_client.get("/api/users/me")).status_code == 401


async def test_admin_cannot_lock_themselves_out(login_as):
    c, admin = await login_as(Role.admin)
    assert (await c.delete(f"/api/users/{admin.id}")).status_code == 400
    assert (await c.patch(f"/api/users/{admin.id}", json={"is_active": False})).status_code == 400
    assert (await c.patch(f"/api/users/{admin.id}", json={"role": "manager"})).status_code == 400
    assert (
        await c.patch(f"/api/users/{admin.id}", json={"full_name": "New Name"})
    ).status_code == 200


async def test_unknown_user_returns_404(login_as):
    c, _ = await login_as(Role.admin)
    assert (await c.get("/api/users/99999")).status_code == 404
    assert (await c.delete("/api/users/99999")).status_code == 404


async def test_cli_create_admin(db):
    from app.cli import create_admin

    user_id = await create_admin("Owner@Flatons.com", "Site Owner", "owner-password-1")

    user = await db.get(User, user_id)
    assert user.role == Role.admin and user.email == "owner@flatons.com"
