from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.core.deps import CurrentUser, DbSession, require_role
from app.models.lead import REASON_REQUIRED, Lead
from app.models.project import Project
from app.models.user import Role, User
from app.schemas.lead import (
    Assignment,
    DuplicateCheck,
    DuplicateOut,
    LeadCreate,
    LeadCreated,
    LeadDetail,
    LeadOut,
    LeadPage,
    LeadSearch,
    LeadUpdate,
    NoteCreate,
    StatusChange,
)
from app.services import leads as svc
from app.services.audit import log_audit

router = APIRouter(prefix="/leads", tags=["leads"])

Writer = Annotated[User, Depends(require_role(Role.admin, Role.manager, Role.executive))]
Manager = Annotated[User, Depends(require_role(Role.admin, Role.manager))]
Admin = Annotated[User, Depends(require_role(Role.admin))]

NOT_FOUND = HTTPException(status.HTTP_404_NOT_FOUND, "Lead not found")


async def _lead_for_edit(db: DbSession, user: User, lead_id: int) -> Lead:
    lead = await svc.get_visible_lead(db, user, lead_id)
    if lead is None:
        raise NOT_FOUND
    if not svc.can_edit(user, lead):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You can't edit this lead")
    return lead


async def _check_project(db: DbSession, project_id: int | None) -> None:
    if project_id is not None:
        project = await db.get(Project, project_id)
        if project is None or not project.is_active:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Choose an active project")


async def _detail(db: DbSession, user: User, lead: Lead) -> LeadDetail:
    await db.refresh(lead)
    activities = await svc.list_activities(db, lead.id)
    return LeadDetail.model_validate(
        {
            **LeadOut.model_validate(lead).model_dump(),
            "activities": activities,
            "can_edit": svc.can_edit(user, lead),
        }
    )


@router.post("/search", response_model=LeadPage)
async def search(body: LeadSearch, user: CurrentUser, db: DbSession) -> LeadPage:
    items, total = await svc.search_leads(db, user, body)
    return LeadPage(items=items, total=total, page=body.page, page_size=body.page_size)


@router.post("/duplicates", response_model=list[DuplicateOut])
async def check_duplicates(
    body: DuplicateCheck, user: CurrentUser, db: DbSession
) -> list[DuplicateOut]:
    return await svc.find_duplicates(
        db,
        user,
        mobiles=[body.mobile, body.alt_mobile],
        email=body.email,
        exclude_id=body.exclude_id,
    )


@router.post("", response_model=LeadCreated, status_code=status.HTTP_201_CREATED)
async def create_lead(
    body: LeadCreate, request: Request, user: Writer, db: DbSession
) -> LeadCreated:
    await _check_project(db, body.project_id)

    assignee_id: int | None = user.id if user.role == Role.executive else body.assigned_to_id
    if assignee_id is not None and assignee_id != user.id:
        try:
            await svc.get_assignable_user(db, assignee_id)
        except svc.LeadRuleError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None

    duplicates = await svc.find_duplicates(
        db, user, mobiles=[body.mobile, body.alt_mobile], email=body.email
    )

    data = body.model_dump(exclude={"assigned_to_id"})
    lead = Lead(
        **data,
        lead_code=await svc.next_lead_code(db),
        assigned_to_id=assignee_id,
        created_by_id=user.id,
    )
    db.add(lead)
    await db.flush()

    details: dict[str, Any] = {"source": lead.source.value}
    if duplicates:
        details["possible_duplicates"] = [d.lead_code for d in duplicates]
    svc.add_activity(db, lead, actor=user, type="created", details=details)
    log_audit(
        db, action="lead.create", entity_type="lead", entity_id=lead.id, actor=user, request=request
    )
    await db.commit()
    await db.refresh(lead)
    return LeadCreated(lead=LeadOut.model_validate(lead), duplicates=duplicates)


@router.get("/{lead_id}", response_model=LeadDetail)
async def get_lead(lead_id: int, user: CurrentUser, db: DbSession) -> LeadDetail:
    lead = await svc.get_visible_lead(db, user, lead_id)
    if lead is None:
        raise NOT_FOUND
    return await _detail(db, user, lead)


# Fields whose old/new values are recorded in the timeline. Contact details are only
# noted as "changed" so phone numbers and emails don't spread into the activity log.
_TRACKED_VALUES = {
    "name",
    "source",
    "sub_source",
    "configuration",
    "budget_min",
    "budget_max",
    "purpose",
    "timeline",
    "estimated_value",
    "city",
    "project_id",
}


@router.patch("/{lead_id}", response_model=LeadDetail)
async def update_lead(lead_id: int, body: LeadUpdate, user: Writer, db: DbSession) -> LeadDetail:
    lead = await _lead_for_edit(db, user, lead_id)
    changes = body.model_dump(exclude_unset=True)
    for required in ("name", "mobile", "source"):
        if required in changes and changes[required] is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, f"{required.title()} can't be empty"
            )
    if "project_id" in changes:
        await _check_project(db, changes["project_id"])

    budget_min = changes.get("budget_min", lead.budget_min)
    budget_max = changes.get("budget_max", lead.budget_max)
    if budget_min is not None and budget_max is not None and budget_min > budget_max:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Minimum budget can't be more than maximum budget",
        )

    changed: dict[str, Any] = {}
    for field, new in changes.items():
        old = getattr(lead, field)
        if old == new:
            continue
        setattr(lead, field, new)
        if field in _TRACKED_VALUES:
            changed[field] = {"from": getattr(old, "value", old), "to": getattr(new, "value", new)}
        else:
            changed[field] = "changed"

    if changed:
        svc.add_activity(db, lead, actor=user, type="updated", details={"changes": changed})
        await db.commit()
    return await _detail(db, user, lead)


@router.post("/{lead_id}/status", response_model=LeadDetail)
async def change_status(
    lead_id: int, body: StatusChange, request: Request, user: Writer, db: DbSession
) -> LeadDetail:
    lead = await _lead_for_edit(db, user, lead_id)
    try:
        svc.check_status_change(user, lead, body.status, body.reason)
    except svc.LeadRuleError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None

    old = lead.status
    lead.status = body.status
    lead.lost_reason = body.reason if body.status in REASON_REQUIRED else None
    details = {"from": old.value, "to": body.status.value}
    if lead.lost_reason:
        details["reason"] = lead.lost_reason
    svc.add_activity(
        db, lead, actor=user, type="status_change", note=body.note or None, details=details
    )
    log_audit(
        db,
        action="lead.status_change",
        entity_type="lead",
        entity_id=lead.id,
        actor=user,
        details=details,
        request=request,
    )
    await db.commit()
    return await _detail(db, user, lead)


@router.post("/{lead_id}/assign", response_model=LeadDetail)
async def assign_lead(
    lead_id: int, body: Assignment, request: Request, user: Manager, db: DbSession
) -> LeadDetail:
    lead = await svc.get_visible_lead(db, user, lead_id)
    if lead is None:
        raise NOT_FOUND
    if body.assigned_to_id == lead.assigned_to_id:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "The lead is already assigned to this person"
        )

    new_user = None
    if body.assigned_to_id is not None:
        try:
            new_user = await svc.get_assignable_user(db, body.assigned_to_id)
        except svc.LeadRuleError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None

    details = {
        "from": {"id": lead.assigned_to.id, "name": lead.assigned_to.full_name}
        if lead.assigned_to
        else None,
        "to": {"id": new_user.id, "name": new_user.full_name} if new_user else None,
    }
    lead.assigned_to_id = body.assigned_to_id
    svc.add_activity(db, lead, actor=user, type="assignment", details=details)
    log_audit(
        db,
        action="lead.assign",
        entity_type="lead",
        entity_id=lead.id,
        actor=user,
        details=details,
        request=request,
    )
    await db.commit()
    return await _detail(db, user, lead)


@router.post("/{lead_id}/notes", response_model=LeadDetail, status_code=status.HTTP_201_CREATED)
async def add_note(lead_id: int, body: NoteCreate, user: Writer, db: DbSession) -> LeadDetail:
    lead = await _lead_for_edit(db, user, lead_id)
    svc.add_activity(db, lead, actor=user, type="note", note=body.note)
    await db.commit()
    return await _detail(db, user, lead)


@router.delete("/{lead_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_lead(lead_id: int, request: Request, user: Admin, db: DbSession) -> None:
    """Soft delete: the lead disappears from every list but stays in the database."""
    lead = await svc.get_visible_lead(db, user, lead_id)
    if lead is None:
        raise NOT_FOUND
    lead.deleted_at = datetime.now(UTC)
    log_audit(
        db,
        action="lead.delete",
        entity_type="lead",
        entity_id=lead.id,
        actor=user,
        details={"lead_code": lead.lead_code},
        request=request,
    )
    await db.commit()
