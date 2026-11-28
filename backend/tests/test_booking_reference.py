from app.models import Role
from tests import test_bookings
from tests.test_bookings import booking_body

flats = test_bookings.flats


async def _setup(login_as, flats, db):
    project, units = flats
    ex, _ = await login_as(Role.executive)
    lead = (
        await ex.post(
            "/api/leads",
            json={
                "name": "Anita Desai",
                "mobile": "9876543210",
                "email": "anita@example.com",
                "source": "99acres",
            },
        )
    ).json()["lead"]
    return ex, lead, units


async def test_non_cash_payments_need_their_reference(login_as, db, flats):
    ex, lead, units = await _setup(login_as, flats, db)
    r = await ex.post(
        "/api/bookings", json=booking_body(lead["id"], units["101"], payment_reference=None)
    )
    assert r.status_code == 422 and "cheque number" in r.text
    r = await ex.post(
        "/api/bookings",
        json=booking_body(lead["id"], units["101"], payment_mode="upi", payment_reference=None),
    )
    assert r.status_code == 422 and "UTR or transaction ID" in r.text
    r = await ex.post(
        "/api/bookings",
        json=booking_body(lead["id"], units["101"], payment_mode="cash", payment_reference=None),
    )
    assert r.status_code == 201, r.text  # cash has no reference


async def test_edits_are_checked_on_the_result(login_as, db, flats):
    ex, lead, units = await _setup(login_as, flats, db)
    b = (
        await ex.post(
            "/api/bookings",
            json=booking_body(
                lead["id"], units["101"], payment_mode="cash", payment_reference=None
            ),
        )
    ).json()
    mgr, _ = await login_as(Role.manager)
    r = await mgr.patch(f"/api/bookings/{b['id']}", json={"payment_mode": "bank_transfer"})
    assert r.status_code == 422 and "UTR" in r.text  # switching from cash needs the reference
    r = await mgr.patch(
        f"/api/bookings/{b['id']}",
        json={"payment_mode": "bank_transfer", "payment_reference": "HDFCN52026112701"},
    )
    assert r.status_code == 200 and r.json()["payment_reference"] == "HDFCN52026112701"
    assert (
        await mgr.patch(f"/api/bookings/{b['id']}", json={"payment_reference": ""})
    ).status_code == 422  # can't blank it later
