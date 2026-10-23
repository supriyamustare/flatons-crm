from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from app.core.deps import DbSession, require_role
from app.models.lead import Lead
from app.models.task import FollowUpTask, TaskStatus
from app.models.user import Role, User
from app.schemas.task import TaskComplete, TaskCreate, TaskOut, TaskPage, TaskQuery, TaskReschedule
from app.services import leads as lead_svc
from app.services import tasks as svc
from app.services.audit import log_audit
from app.services.notifications import notify

router = APIRouter(prefix="/tasks", tags=["follow-ups"])

# Follow-ups are sales work: documents staff don't use them.
SalesUser = Annotated[User, Depends(require_role(Role.admin, Role.manager, Role.executive))]

TYPE_LABELS = {
    "call": "Call",
    "whatsapp": "WhatsApp",
    "meeting": "Meeting",
    "site_visit": "Site visit",
    "email": "Email",
    "other": "Follow-up",
}


def _rule_error(exc: Exception) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))


async def _task_for_action(db: DbSession, user: User, task_id: int) -> FollowUpTask:
    task = await db.scalar(svc.visible_tasks(user).where(FollowUpTask.id == task_id))
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Follow-up not found")
    if not svc.can_act_on(user, task):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You can't change this follow-up")
    try:
        svc.require_pending(task)
    except svc.TaskRuleError as exc:
        raise _rule_error(exc) from None
    return task


def _when(dt: datetime) -> str:
    return dt.astimezone(lead_svc.IST).strftime("%-d %b, %-I:%M %p")


@router.get("", response_model=TaskPage)
async def list_tasks(q: Annotated[TaskQuery, Query()], user: SalesUser, db: DbSession) -> TaskPage:
    now = datetime.now(UTC)
    items, total, counts = await svc.search_tasks(db, user, q, now)
    return TaskPage(
        items=[svc.to_out(t, now) for t in items],
        total=total,
        page=q.page,
        page_size=q.page_size,
        counts=counts,
    )


@router.post("", response_model=TaskOut, status_code=status.HTTP_201_CREATED)
async def create_task(
    body: TaskCreate, request: Request, user: SalesUser, db: DbSession
) -> TaskOut:
    lead: Lead | None = await lead_svc.get_visible_lead(db, user, body.lead_id)
    if lead is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Lead not found")
    if not lead_svc.can_edit(user, lead):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You can't add follow-ups to this lead")
    try:
        svc.check_due_at(body.due_at)
    except svc.TaskRuleError as exc:
        raise _rule_error(exc) from None

    if user.role in lead_svc.MANAGERS:
        assignee_id = body.assigned_to_id or lead.assigned_to_id or user.id
    else:
        assignee_id = user.id
    assignee = user
    if assignee_id != user.id:
        try:
            assignee = await lead_svc.get_assignable_user(db, assignee_id)
        except lead_svc.LeadRuleError as exc:
            raise _rule_error(exc) from None

    task = FollowUpTask(
        lead_id=lead.id,
        task_type=body.task_type,
        due_at=body.due_at,
        notes=body.notes or None,
        assigned_to_id=assignee.id,
        created_by_id=user.id,
    )
    db.add(task)
    await db.flush()

    label = TYPE_LABELS[body.task_type.value]
    lead_svc.add_activity(
        db,
        lead,
        actor=user,
        type="task_created",
        note=task.notes,
        details={
            "task_id": task.id,
            "task_type": body.task_type.value,
            "due_at": body.due_at.isoformat(),
            "assigned_to": assignee.full_name,
        },
    )
    if assignee.id != user.id:
        notify(
            db,
            user_id=assignee.id,
            type="task_assigned",
            title=f"{label} with {lead.name}",
            body=f"{user.full_name} gave you a follow-up due {_when(body.due_at)}",
            link=f"/leads/{lead.id}",
        )
    log_audit(
        db,
        action="task.create",
        entity_type="task",
        entity_id=task.id,
        actor=user,
        details={"lead_id": lead.id, "assigned_to_id": assignee.id},
        request=request,
    )
    await db.commit()
    await db.refresh(task)
    return svc.to_out(task)


@router.post("/{task_id}/complete", response_model=TaskOut)
async def complete_task(
    task_id: int, body: TaskComplete, request: Request, user: SalesUser, db: DbSession
) -> TaskOut:
    task = await _task_for_action(db, user, task_id)
    task.status = TaskStatus.completed
    task.completed_at = datetime.now(UTC)
    task.completed_by_id = user.id
    task.completion_note = body.completion_note
    lead_svc.add_activity(
        db,
        task.lead,
        actor=user,
        type="task_completed",
        note=body.completion_note,
        details={
            "task_id": task.id,
            "task_type": task.task_type.value,
            "was_overdue": task.due_at < task.completed_at,
        },
    )
    log_audit(
        db,
        action="task.complete",
        entity_type="task",
        entity_id=task.id,
        actor=user,
        request=request,
    )
    await db.commit()
    await db.refresh(task)
    return svc.to_out(task)


@router.post("/{task_id}/reschedule", response_model=TaskOut, status_code=status.HTTP_201_CREATED)
async def reschedule_task(
    task_id: int, body: TaskReschedule, request: Request, user: SalesUser, db: DbSession
) -> TaskOut:
    """Close this task as "rescheduled" and create its replacement, linked back to it,
    so the full history of postponements is kept."""
    task = await _task_for_action(db, user, task_id)
    try:
        svc.check_due_at(body.due_at)
    except svc.TaskRuleError as exc:
        raise _rule_error(exc) from None

    task.status = TaskStatus.rescheduled
    new_task = FollowUpTask(
        lead_id=task.lead_id,
        task_type=task.task_type,
        due_at=body.due_at,
        notes=task.notes,
        assigned_to_id=task.assigned_to_id,
        created_by_id=user.id,
        rescheduled_from_id=task.id,
        reschedule_reason=body.reason,
    )
    db.add(new_task)
    await db.flush()
    lead_svc.add_activity(
        db,
        task.lead,
        actor=user,
        type="task_rescheduled",
        note=body.reason,
        details={
            "task_id": new_task.id,
            "previous_task_id": task.id,
            "task_type": task.task_type.value,
            "from": task.due_at.isoformat(),
            "to": body.due_at.isoformat(),
        },
    )
    log_audit(
        db,
        action="task.reschedule",
        entity_type="task",
        entity_id=new_task.id,
        actor=user,
        details={"previous_task_id": task.id},
        request=request,
    )
    await db.commit()
    await db.refresh(new_task)
    return svc.to_out(new_task)
