from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select

from app.core.crypto import encrypt
from app.core.deps import DbSession, require_role
from app.models.integration import InboundEvent, Integration, IntegrationKind
from app.models.lead import Lead, LeadStatus
from app.models.marketing import Campaign
from app.models.project import Project
from app.models.user import Role, User
from app.schemas.integration import (
    InboundEventOut,
    Inbox,
    InboxItem,
    IntegrationCreate,
    IntegrationCreated,
    IntegrationOut,
    IntegrationUpdate,
)
from app.schemas.lead import CampaignBrief
from app.schemas.project import ProjectBrief
from app.services import inbound as svc
from app.services.audit import log_audit

router = APIRouter(tags=["integrations"])
Admin = Annotated[User, Depends(require_role(Role.admin))]
Manager = Annotated[User, Depends(require_role(Role.admin, Role.manager))]


def _out(i: Integration) -> IntegrationOut:
    out = IntegrationOut.model_validate(i)
    out.facebook_ready = bool(i.fb_app_secret_enc and i.fb_page_token_enc)
    out.path = f"/api/inbound/{i.id}" + ("/facebook" if i.kind == IntegrationKind.facebook else "")
    return out


async def _check_defaults(db: DbSession, campaign_id: int | None, project_id: int | None) -> None:
    if campaign_id is not None and await db.get(Campaign, campaign_id) is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "That campaign doesn't exist")
    if project_id is not None and await db.get(Project, project_id) is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "That project doesn't exist")


async def _get(db: DbSession, integration_id: int) -> Integration:
    i = await db.get(Integration, integration_id)
    if i is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Connection not found")
    return i


@router.get("/integrations", response_model=list[IntegrationOut])
async def list_integrations(_: Admin, db: DbSession) -> list[IntegrationOut]:
    return [_out(i) for i in await db.scalars(select(Integration).order_by(Integration.name))]


@router.post(
    "/integrations", response_model=IntegrationCreated, status_code=status.HTTP_201_CREATED
)
async def create_integration(
    body: IntegrationCreate, request: Request, admin: Admin, db: DbSession
) -> IntegrationCreated:
    if await db.scalar(select(Integration.id).where(Integration.name.ilike(body.name))):
        raise HTTPException(status.HTTP_409_CONFLICT, "A connection with this name already exists")
    await _check_defaults(db, body.default_campaign_id, body.default_project_id)
    secret = svc.new_secret()
    i = Integration(
        name=body.name,
        kind=body.kind,
        secret_hash=svc.hash_secret(secret),
        default_campaign_id=body.default_campaign_id,
        default_project_id=body.default_project_id,
        fb_app_secret_enc=encrypt(body.fb_app_secret) if body.fb_app_secret else None,
        fb_page_token_enc=encrypt(body.fb_page_token) if body.fb_page_token else None,
        created_by_id=admin.id,
    )
    db.add(i)
    await db.flush()
    log_audit(
        db,
        action="integration.create",
        entity_type="integration",
        entity_id=i.id,
        actor=admin,
        details={"name": i.name, "kind": i.kind.value},
        request=request,
    )
    await db.commit()
    await db.refresh(i)
    return IntegrationCreated(integration=_out(i), secret=secret)


@router.patch("/integrations/{integration_id}", response_model=IntegrationOut)
async def update_integration(
    integration_id: int, body: IntegrationUpdate, request: Request, admin: Admin, db: DbSession
) -> IntegrationOut:
    i = await _get(db, integration_id)
    changes = body.model_dump(exclude_unset=True)
    await _check_defaults(db, changes.get("default_campaign_id"), changes.get("default_project_id"))
    for k in ("name", "is_active", "default_campaign_id", "default_project_id"):
        if k in changes:
            setattr(i, k, changes[k])
    if changes.get("fb_app_secret"):
        i.fb_app_secret_enc = encrypt(changes["fb_app_secret"])
    if changes.get("fb_page_token"):
        i.fb_page_token_enc = encrypt(changes["fb_page_token"])
    shown = {k: ("(changed)" if k.startswith("fb_") else v) for k, v in changes.items()}
    log_audit(
        db,
        action="integration.update",
        entity_type="integration",
        entity_id=i.id,
        actor=admin,
        details=shown,
        request=request,
    )
    await db.commit()
    await db.refresh(i)
    return _out(i)


@router.post("/integrations/{integration_id}/rotate", response_model=IntegrationCreated)
async def rotate_secret(
    integration_id: int, request: Request, admin: Admin, db: DbSession
) -> IntegrationCreated:
    """New secret key; the old one stops working immediately."""
    i = await _get(db, integration_id)
    secret = svc.new_secret()
    i.secret_hash = svc.hash_secret(secret)
    log_audit(
        db,
        action="integration.rotate",
        entity_type="integration",
        entity_id=i.id,
        actor=admin,
        request=request,
    )
    await db.commit()
    await db.refresh(i)
    return IntegrationCreated(integration=_out(i), secret=secret)


@router.get("/integrations/{integration_id}/events", response_model=list[InboundEventOut])
async def recent_events(
    integration_id: int, _: Admin, db: DbSession, limit: Annotated[int, Query(ge=1, le=200)] = 50
) -> list[InboundEvent]:
    await _get(db, integration_id)
    return list(
        await db.scalars(
            select(InboundEvent)
            .where(InboundEvent.integration_id == integration_id)
            .order_by(InboundEvent.received_at.desc(), InboundEvent.id.desc())
            .limit(limit)
        )
    )


# ---- Inbox: new, unassigned leads waiting for a manager to hand out ---------


def _inbox_filter():
    return (
        Lead.deleted_at.is_(None),
        Lead.assigned_to_id.is_(None),
        Lead.status.notin_([LeadStatus.lost, LeadStatus.junk, LeadStatus.booked]),
    )


@router.get("/inbox", response_model=Inbox)
async def inbox(_: Manager, db: DbSession) -> Inbox:
    count = await db.scalar(select(func.count()).select_from(Lead).where(*_inbox_filter())) or 0
    leads = await db.scalars(
        select(Lead).where(*_inbox_filter()).order_by(Lead.created_at.desc()).limit(100)
    )
    return Inbox(
        count=count,
        items=[
            InboxItem(
                id=lead.id,
                lead_code=lead.lead_code,
                name=lead.name,
                mobile=lead.mobile,
                source=lead.source.value,
                sub_source=lead.sub_source,
                message=lead.remarks,
                created_at=lead.created_at,
                project=ProjectBrief.model_validate(lead.project) if lead.project else None,
                campaign=CampaignBrief.model_validate(lead.campaign) if lead.campaign else None,
            )
            for lead in leads
        ],
    )


@router.get("/inbox/count")
async def inbox_count(_: Manager, db: DbSession) -> dict:
    """Lightweight count for the menu badge (polled)."""
    return {
        "count": await db.scalar(select(func.count()).select_from(Lead).where(*_inbox_filter()))
        or 0
    }
