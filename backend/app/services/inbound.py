"""Turning enquiries from outside platforms into leads.

Each platform has an adapter that turns its format into `Enquiry`. Then `ingest()` applies the
same rules for all of them: a valid phone number is required; a number that matches an existing
lead adds the enquiry to that lead and alerts its owner; otherwise a new, unassigned lead is
created for a manager to hand out from the inbox.
"""

import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.integration import InboundEvent, InboundStatus, Integration, IntegrationKind
from app.models.lead import Lead, LeadSource, LeadStatus
from app.models.user import Role, User
from app.schemas.common import normalize_mobile
from app.services.audit import log_audit
from app.services.leads import add_activity, next_lead_code
from app.services.notifications import notify

KIND_LABELS = {
    IntegrationKind.website: "website",
    IntegrationKind.portal_99acres: "99acres",
    IntegrationKind.magicbricks: "MagicBricks",
    IntegrationKind.housing: "Housing.com",
    IntegrationKind.facebook: "Facebook / Instagram",
    IntegrationKind.google_ads: "Google Ads",
}
KIND_SOURCE = {
    IntegrationKind.website: LeadSource.website,
    IntegrationKind.portal_99acres: LeadSource.acres_99,
    IntegrationKind.magicbricks: LeadSource.magicbricks,
    IntegrationKind.housing: LeadSource.housing,
    IntegrationKind.facebook: LeadSource.social,
    IntegrationKind.google_ads: LeadSource.google_ads,
}
EMAIL_RE = re.compile(r"^[^@\s<>]+@[^@\s<>]+\.[^@\s<>]+$")


class InboundError(ValueError):
    """The payload can't be used; the message is returned to the sender and logged."""


@dataclass
class Enquiry:
    name: str | None = None
    mobile: str | None = None
    email: str | None = None
    city: str | None = None
    message: str | None = None
    external_id: str | None = None
    sub_source: str | None = None  # e.g. the ad, form or listing it came from
    extra: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------- secrets


def new_secret() -> str:
    return secrets.token_urlsafe(32)


def hash_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def secret_matches(integration: Integration, given: str | None) -> bool:
    return bool(given) and hmac.compare_digest(integration.secret_hash, hash_secret(given))


def facebook_signature_ok(app_secret: str, body: bytes, header: str | None) -> bool:
    if not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(app_secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header.removeprefix("sha256="))


# ---------------------------------------------------------------- adapters

GENERIC_KEYS = {
    "name": (
        "name",
        "full_name",
        "fullname",
        "customer_name",
        "contact_name",
        "lead_name",
        "sender_name",
    ),
    "mobile": (
        "mobile",
        "phone",
        "phone_number",
        "mobile_no",
        "mobile_number",
        "contact",
        "contact_number",
        "contact_no",
        "sender_mobile",
    ),
    "email": ("email", "email_id", "email_address", "sender_email"),
    "city": ("city", "location", "locality", "city_name"),
    "message": (
        "message",
        "comments",
        "comment",
        "query",
        "enquiry",
        "inquiry",
        "remarks",
        "requirement",
    ),
    "external_id": ("id", "lead_id", "enquiry_id", "inquiry_id", "query_id", "response_id"),
    "sub_source": (
        "project",
        "project_name",
        "property",
        "property_name",
        "listing",
        "listing_name",
        "form",
        "form_name",
    ),
}


def _first(d: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    lower = {str(k).lower(): v for k, v in d.items()}
    for k in keys:
        v = lower.get(k)
        if v not in (None, "", []):
            return str(v)
    return None


def parse_generic(payload: Any) -> list[Enquiry]:
    """Website form and property portals: flat JSON with common field names (see GENERIC_KEYS),
    one enquiry per request or a list under "leads"."""
    if isinstance(payload, dict) and isinstance(payload.get("leads"), list):
        items = payload["leads"]
    elif isinstance(payload, list):
        items = payload
    else:
        items = [payload]
    out = []
    for item in items[:50]:
        if not isinstance(item, dict):
            raise InboundError("Each enquiry must be a JSON object")
        out.append(Enquiry(**{f: _first(item, keys) for f, keys in GENERIC_KEYS.items()}))
    return out


def parse_google(payload: dict[str, Any]) -> tuple[Enquiry, bool]:
    """Google Ads lead form webhook. Returns (enquiry, is_test)."""
    cols = {
        c.get("column_id"): c.get("string_value")
        for c in payload.get("user_column_data") or []
        if isinstance(c, dict)
    }
    first, last = cols.get("FIRST_NAME"), cols.get("LAST_NAME")
    name = cols.get("FULL_NAME") or " ".join(p for p in (first, last) if p) or None
    return (
        Enquiry(
            name=name,
            mobile=cols.get("PHONE_NUMBER"),
            email=cols.get("EMAIL"),
            city=cols.get("CITY"),
            external_id=str(payload.get("lead_id") or "") or None,
            sub_source=f"Google form {payload.get('form_id')}" if payload.get("form_id") else None,
        ),
        bool(payload.get("is_test")),
    )


def parse_facebook_lead(data: dict[str, Any]) -> Enquiry:
    """A lead fetched from the Graph API: {"id", "field_data": [{"name", "values": [...]}]}."""
    fields = {
        f.get("name"): (f.get("values") or [None])[0]
        for f in data.get("field_data") or []
        if isinstance(f, dict)
    }
    first, last = fields.get("first_name"), fields.get("last_name")
    return Enquiry(
        name=fields.get("full_name") or " ".join(p for p in (first, last) if p) or None,
        mobile=fields.get("phone_number") or fields.get("mobile_number"),
        email=fields.get("email"),
        city=fields.get("city"),
        external_id=str(data.get("id") or "") or None,
        sub_source=f"Facebook form {data['form_id']}" if data.get("form_id") else None,
    )


# ---------------------------------------------------------------- the shared rules


def _clean(text: str | None, limit: int) -> str | None:
    if not text:
        return None
    text = re.sub(r"[<>]", "", str(text)).strip()
    return text[:limit] or None


async def _alert(db: AsyncSession, lead: Lead, integration: Integration, enq: Enquiry) -> None:
    """Tell the lead's owner about a repeat enquiry; if nobody owns it, tell managers and admins."""
    if lead.assigned_to_id:
        owners = [lead.assigned_to_id]
    else:
        owners = list(
            await db.scalars(
                select(User.id).where(
                    User.is_active.is_(True), User.role.in_([Role.admin, Role.manager])
                )
            )
        )
    closed = (
        f" (currently {lead.status.value.replace('_', ' ')})"
        if lead.status in (LeadStatus.lost, LeadStatus.junk, LeadStatus.booked)
        else ""
    )
    for uid in owners:
        notify(
            db,
            user_id=uid,
            type="repeat_enquiry",
            title=f"{lead.name} enquired again",
            body=f"New enquiry from {KIND_LABELS[integration.kind]} for {lead.lead_code}{closed}",
            link=f"/leads/{lead.id}",
        )


async def ingest(
    db: AsyncSession,
    integration: Integration,
    enq: Enquiry,
    payload: dict[str, Any],
    *,
    test: bool = False,
    event: InboundEvent | None = None,
) -> InboundEvent:
    """Record the enquiry and create or update a lead. The caller commits."""
    now = datetime.now(UTC)
    if event is None:
        if enq.external_id:
            seen = await db.scalar(
                select(InboundEvent).where(
                    InboundEvent.integration_id == integration.id,
                    InboundEvent.external_id == enq.external_id,
                )
            )
            if seen is not None:
                return seen  # the platform re-sent something we already have; do nothing
        event = InboundEvent(
            integration_id=integration.id,
            external_id=enq.external_id,
            payload=payload,
            status=InboundStatus.pending,
        )
        db.add(event)
    integration.received_count += 1
    integration.last_received_at = now

    try:
        mobile = normalize_mobile(enq.mobile or "")
    except ValueError:
        event.status, event.error = InboundStatus.rejected, "No valid phone number in the enquiry"
        await db.flush()
        return event
    email = enq.email.strip().lower() if enq.email and EMAIL_RE.match(enq.email.strip()) else None
    name = _clean(enq.name, 150) or f"Enquiry from {KIND_LABELS[integration.kind]}"
    message = _clean(enq.message, 2000)
    if test:
        event.status, event.error = InboundStatus.test, f"Test only. Would use: {name}, {mobile}"
        await db.flush()
        return event

    existing = await db.scalar(
        select(Lead)
        .where(Lead.deleted_at.is_(None), or_(Lead.mobile == mobile, Lead.alt_mobile == mobile))
        .order_by(Lead.last_activity_at.desc())
        .limit(1)
    )
    via = {"via": integration.name, "kind": integration.kind.value}
    if existing is not None:
        add_activity(
            db,
            existing,
            actor=None,
            type="enquiry",
            note=message,
            details={
                **via,
                "name": name,
                "email": email,
                "sub_source": _clean(enq.sub_source, 150),
            },
        )
        await _alert(db, existing, integration, enq)
        event.status, event.lead_id = InboundStatus.merged, existing.id
        await db.flush()
        return event

    lead = Lead(
        lead_code=await next_lead_code(db, now),
        name=name,
        mobile=mobile,
        email=email,
        city=_clean(enq.city, 150),
        source=KIND_SOURCE[integration.kind],
        sub_source=_clean(enq.sub_source, 150),
        campaign_id=integration.default_campaign_id,
        project_id=integration.default_project_id,
        remarks=message,
        status=LeadStatus.new,
        assigned_to_id=None,
        created_by_id=None,
    )
    db.add(lead)
    await db.flush()
    add_activity(
        db,
        lead,
        actor=None,
        type="created",
        note=message,
        details={**via, "source": lead.source.value},
    )
    log_audit(db, action="lead.inbound", entity_type="lead", entity_id=lead.id, details=via)
    event.status, event.lead_id = InboundStatus.created, lead.id
    await db.flush()
    return event
