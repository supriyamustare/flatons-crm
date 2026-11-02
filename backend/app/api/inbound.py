"""Public endpoints that platforms send enquiries to.

No login here: each connection has its own secret key."""

import json
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import PlainTextResponse
from sqlalchemy import select

from app.core.crypto import decrypt
from app.core.deps import DbSession
from app.models.integration import InboundEvent, InboundStatus, Integration, IntegrationKind
from app.services import inbound as svc

router = APIRouter(prefix="/inbound", tags=["incoming enquiries"])
MAX_BODY = 64 * 1024
UNAUTHORIZED = HTTPException(status.HTTP_401_UNAUTHORIZED, "Unknown connection or wrong key")


async def _body(request: Request) -> tuple[bytes, Any]:
    raw = await request.body()
    if len(raw) > MAX_BODY:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "Request too large")
    try:
        return raw, json.loads(raw or b"null")
    except ValueError:
        # Some portals post form fields instead of JSON
        form = await request.form()
        return raw, dict(form)


async def _connection(db: DbSession, integration_id: int) -> Integration:
    integration = await db.get(Integration, integration_id)
    if integration is None:
        raise UNAUTHORIZED
    return integration


def _result(e: InboundEvent) -> dict:
    return {"status": e.status.value, "lead_id": e.lead_id, "detail": e.error}


@router.post("/{integration_id}")
async def receive(
    integration_id: int,
    request: Request,
    db: DbSession,
    key: str | None = Query(None),
    test: bool = Query(False),
) -> dict:
    """Website form, property portals and Google Ads. Key in the X-Flatons-Key header, ?key=,
    or (Google) the google_key field."""
    integration = await _connection(db, integration_id)
    raw, payload = await _body(request)
    given = request.headers.get("x-flatons-key") or key
    if integration.kind == IntegrationKind.google_ads and isinstance(payload, dict):
        given = given or payload.get("google_key")
    if not svc.secret_matches(integration, given):
        raise UNAUTHORIZED
    if not integration.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This connection is switched off")
    if integration.kind == IntegrationKind.facebook:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Facebook connections use the /facebook address"
        )
    safe_payload = (
        {k: v for k, v in payload.items() if k != "google_key"}
        if isinstance(payload, dict)
        else {"items": payload}
    )
    try:
        if integration.kind == IntegrationKind.google_ads:
            if not isinstance(payload, dict):
                raise svc.InboundError("Expected a JSON object")
            enq, is_test = svc.parse_google(payload)
            enquiries, test = [enq], test or is_test
        else:
            enquiries = svc.parse_generic(payload)
    except svc.InboundError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
    results = [
        _result(await svc.ingest(db, integration, e, safe_payload, test=test)) for e in enquiries
    ]
    await db.commit()
    return results[0] if len(results) == 1 else {"results": results}


@router.get("/{integration_id}/facebook", response_class=PlainTextResponse)
async def facebook_verify(
    integration_id: int,
    db: DbSession,
    mode: str = Query(alias="hub.mode"),
    token: str = Query(alias="hub.verify_token"),
    challenge: str = Query(alias="hub.challenge"),
) -> str:
    """Facebook checks this address once at setup; the verify token is the secret key."""
    integration = await _connection(db, integration_id)
    if (
        mode != "subscribe"
        or integration.kind != IntegrationKind.facebook
        or not svc.secret_matches(integration, token)
    ):
        raise UNAUTHORIZED
    return challenge


@router.post("/{integration_id}/facebook")
async def facebook_receive(integration_id: int, request: Request, db: DbSession) -> dict:
    integration = await _connection(db, integration_id)
    raw, payload = await _body(request)
    app_secret = decrypt(integration.fb_app_secret_enc or "")
    if (
        integration.kind != IntegrationKind.facebook
        or not app_secret
        or not svc.facebook_signature_ok(
            app_secret, raw, request.headers.get("x-hub-signature-256")
        )
    ):
        raise UNAUTHORIZED
    if not integration.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This connection is switched off")
    from app.tasks.inbound import facebook_lead

    queued = []
    for entry in (payload or {}).get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value") or {}
            leadgen_id = str(value.get("leadgen_id") or "")
            if change.get("field") != "leadgen" or not leadgen_id:
                continue
            if await db.scalar(
                select(InboundEvent.id).where(
                    InboundEvent.integration_id == integration.id,
                    InboundEvent.external_id == leadgen_id,
                )
            ):
                continue  # Facebook re-sent it
            event = InboundEvent(
                integration_id=integration.id,
                external_id=leadgen_id,
                payload=value,
                status=InboundStatus.pending,
            )
            db.add(event)
            integration.received_count += 1
            await db.flush()
            queued.append(event.id)
    await db.commit()
    for event_id in queued:
        facebook_lead.delay(event_id)
    return {"received": len(queued)}
