from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from app.core.deps import DbSession, require_role
from app.models.project import Project
from app.models.user import Role, User
from app.models.visit import SiteVisit, VisitStatus
from app.schemas.visit import (
    VisitCancel,
    VisitComplete,
    VisitCounts,
    VisitCreate,
    VisitNoShow,
    VisitOut,
    VisitPage,
    VisitQuery,
    VisitReschedule,
)
from app.services import leads as lead_svc
from app.services import tasks as task_svc
from app.services import visits as svc
from app.services.audit import log_audit
from app.services.notifications import notify

router = APIRouter(prefix="/visits", tags=["site visits"])
SalesUser = Annotated[User, Depends(require_role(Role.admin, Role.manager, Role.executive))]


def _unprocessable(msg: str) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, msg)


async def _visit_for_action(db: DbSession, user: User, visit_id: int) -> SiteVisit:
    visit = await db.scalar(svc.visible_visits(user).where(SiteVisit.id == visit_id))
    if visit is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Visit not found")
    if not svc.can_act_on(user, visit):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You can't change this visit")
    try:
        svc.require_scheduled(visit)
    except svc.VisitRuleError as exc:
        raise _unprocessable(str(exc)) from None
    return visit


async def _finish(db: DbSession, visit: SiteVisit) -> VisitOut:
    await db.commit()
    await db.refresh(visit)
    return svc.to_out(visit)


@router.get("", response_model=VisitPage)
async def list_visits(
    q: Annotated[VisitQuery, Query()], user: SalesUser, db: DbSession
) -> VisitPage:
    now = datetime.now(UTC)
    items, total, upcoming, needs_update = await svc.search_visits(db, user, q, now)
    return VisitPage(
        items=[svc.to_out(v, now) for v in items],
        total=total,
        page=q.page,
        page_size=q.page_size,
        counts=VisitCounts(upcoming=upcoming, needs_update=needs_update),
    )


@router.post("", response_model=VisitOut, status_code=status.HTTP_201_CREATED)
async def schedule_visit(
    body: VisitCreate, request: Request, user: SalesUser, db: DbSession
) -> VisitOut:
    lead = await lead_svc.get_visible_lead(db, user, body.lead_id)
    if lead is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Lead not found")
    if not lead_svc.can_edit(user, lead):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You can't schedule visits for this lead")
    project = await db.get(Project, body.project_id)
    if project is None or not project.is_active:
        raise _unprocessable("Choose an active project")
    try:
        task_svc.check_due_at(body.scheduled_at)
    except task_svc.TaskRuleError:
        raise _unprocessable("Choose a future date and time for the visit") from None

    if user.role in lead_svc.MANAGERS:
        host_id = body.host_id or lead.assigned_to_id or user.id
    else:
        host_id = user.id
    host = user
    if host_id != user.id:
        try:
            host = await lead_svc.get_assignable_user(db, host_id)
        except lead_svc.LeadRuleError as exc:
            raise _unprocessable(str(exc)) from None

    visit = SiteVisit(
        lead_id=lead.id,
        project_id=project.id,
        host_id=host.id,
        created_by_id=user.id,
        visit_source=body.visit_source,
        scheduled_at=body.scheduled_at,
        notes=body.notes or None,
    )
    db.add(visit)
    await db.flush()
    lead_svc.add_activity(
        db,
        lead,
        actor=user,
        type="visit_scheduled",
        note=visit.notes,
        details={
            "visit_id": visit.id,
            "project": project.name,
            "scheduled_at": body.scheduled_at.isoformat(),
            "host": host.full_name,
            "visit_source": body.visit_source.value,
        },
    )
    await svc.advance_lead_status(db, lead, event="scheduled", actor=user, request=request)
    if host.id != user.id:
        notify(
            db,
            user_id=host.id,
            type="visit_assigned",
            title=f"Site visit: {lead.name}",
            body=f"{project.name}, {task_svc.format_when(body.scheduled_at)}. "
            f"Scheduled by {user.full_name}",
            link=f"/leads/{lead.id}",
        )
    log_audit(
        db,
        action="visit.schedule",
        entity_type="visit",
        entity_id=visit.id,
        actor=user,
        details={"lead_id": lead.id, "project_id": project.id, "host_id": host.id},
        request=request,
    )
    return await _finish(db, visit)


@router.post("/{visit_id}/complete", response_model=VisitOut)
async def complete_visit(
    visit_id: int, body: VisitComplete, request: Request, user: SalesUser, db: DbSession
) -> VisitOut:
    visit = await _visit_for_action(db, user, visit_id)
    try:
        svc.require_visit_day_reached(visit)
        if body.follow_up_at is not None:
            task_svc.check_due_at(body.follow_up_at)
    except (svc.VisitRuleError, task_svc.TaskRuleError) as exc:
        raise _unprocessable(str(exc)) from None

    visit.status = VisitStatus.completed
    visit.feedback = body.feedback
    visit.interest_level = body.interest_level
    visit.next_action = body.next_action
    visit.closed_at = datetime.now(UTC)
    visit.closed_by_id = user.id
    await db.flush()
    lead_svc.add_activity(
        db,
        visit.lead,
        actor=user,
        type="visit_completed",
        note=body.feedback,
        details={
            "visit_id": visit.id,
            "project": visit.project.name,
            "interest_level": body.interest_level.value,
            "next_action": body.next_action,
        },
    )
    await svc.advance_lead_status(db, visit.lead, event="completed", actor=user, request=request)
    if body.follow_up_at is not None:
        await task_svc.create_follow_up(
            db,
            lead=visit.lead,
            actor=user,
            task_type=body.follow_up_type,
            due_at=body.follow_up_at,
            notes=body.next_action or "After site visit",
            source="visit",
        )
    log_audit(
        db,
        action="visit.complete",
        entity_type="visit",
        entity_id=visit.id,
        actor=user,
        request=request,
    )
    return await _finish(db, visit)


@router.post("/{visit_id}/reschedule", response_model=VisitOut)
async def reschedule_visit(
    visit_id: int, body: VisitReschedule, request: Request, user: SalesUser, db: DbSession
) -> VisitOut:
    visit = await _visit_for_action(db, user, visit_id)
    try:
        task_svc.check_due_at(body.scheduled_at)
    except task_svc.TaskRuleError:
        raise _unprocessable("Choose a future date and time for the visit") from None
    old = visit.scheduled_at
    visit.scheduled_at = body.scheduled_at
    visit.reschedule_count += 1
    lead_svc.add_activity(
        db,
        visit.lead,
        actor=user,
        type="visit_rescheduled",
        note=body.reason,
        details={
            "visit_id": visit.id,
            "project": visit.project.name,
            "from": old.isoformat(),
            "to": body.scheduled_at.isoformat(),
        },
    )
    log_audit(
        db,
        action="visit.reschedule",
        entity_type="visit",
        entity_id=visit.id,
        actor=user,
        request=request,
    )
    return await _finish(db, visit)


@router.post("/{visit_id}/no-show", response_model=VisitOut)
async def visit_no_show(
    visit_id: int, body: VisitNoShow, request: Request, user: SalesUser, db: DbSession
) -> VisitOut:
    visit = await _visit_for_action(db, user, visit_id)
    try:
        svc.require_visit_day_reached(visit)
    except svc.VisitRuleError as exc:
        raise _unprocessable(str(exc)) from None
    visit.status = VisitStatus.no_show
    visit.feedback = body.note
    visit.closed_at = datetime.now(UTC)
    visit.closed_by_id = user.id
    lead_svc.add_activity(
        db,
        visit.lead,
        actor=user,
        type="visit_no_show",
        note=body.note,
        details={"visit_id": visit.id, "project": visit.project.name},
    )
    log_audit(
        db,
        action="visit.no_show",
        entity_type="visit",
        entity_id=visit.id,
        actor=user,
        request=request,
    )
    return await _finish(db, visit)


@router.post("/{visit_id}/cancel", response_model=VisitOut)
async def cancel_visit(
    visit_id: int, body: VisitCancel, request: Request, user: SalesUser, db: DbSession
) -> VisitOut:
    visit = await _visit_for_action(db, user, visit_id)
    visit.status = VisitStatus.cancelled
    visit.cancellation_reason = body.reason
    visit.closed_at = datetime.now(UTC)
    visit.closed_by_id = user.id
    lead_svc.add_activity(
        db,
        visit.lead,
        actor=user,
        type="visit_cancelled",
        note=body.reason,
        details={"visit_id": visit.id, "project": visit.project.name},
    )
    log_audit(
        db,
        action="visit.cancel",
        entity_type="visit",
        entity_id=visit.id,
        actor=user,
        details={"reason": body.reason},
        request=request,
    )
    return await _finish(db, visit)
