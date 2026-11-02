from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from app.core.deps import DbSession, require_role
from app.models.call import CallLog
from app.models.task import FollowUpTask, TaskStatus
from app.models.user import Role, User
from app.schemas.call import CallCreate, CallOut, CallPage, CallQuery
from app.services import calls as svc
from app.services import leads as lead_svc
from app.services import tasks as task_svc
from app.services.audit import log_audit

router = APIRouter(prefix="/calls", tags=["calls"])
SalesUser = Annotated[User, Depends(require_role(Role.admin, Role.manager, Role.executive))]

# Calls can be logged after the fact, but not for the future or far in the past.
FUTURE_GRACE = timedelta(minutes=5)
MAX_BACKDATE = timedelta(days=30)


def _unprocessable(msg: str) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, msg)


@router.get("", response_model=CallPage)
async def list_calls(q: Annotated[CallQuery, Query()], user: SalesUser, db: DbSession) -> CallPage:
    items, total, connected = await svc.search_calls(db, user, q)
    return CallPage(
        items=[svc.to_out(c) for c in items],
        total=total,
        page=q.page,
        page_size=q.page_size,
        connected=connected,
    )


@router.post("", response_model=CallOut, status_code=status.HTTP_201_CREATED)
async def log_call(body: CallCreate, request: Request, user: SalesUser, db: DbSession) -> CallOut:
    lead = await lead_svc.get_visible_lead(db, user, body.lead_id)
    if lead is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Lead not found")
    if not lead_svc.can_edit(user, lead):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You can't log calls on this lead")

    now = datetime.now(UTC)
    called_at = body.called_at or now
    if called_at > now + FUTURE_GRACE:
        raise _unprocessable("The call time can't be in the future")
    if called_at < now - MAX_BACKDATE:
        raise _unprocessable("Calls older than 30 days can't be logged")
    if body.follow_up_at is not None:
        try:
            task_svc.check_due_at(body.follow_up_at, now)
        except task_svc.TaskRuleError:
            raise _unprocessable("Choose a future time for the next follow-up") from None

    task_to_close: FollowUpTask | None = None
    if body.complete_task_id is not None:
        task_to_close = await db.scalar(
            task_svc.visible_tasks(user).where(FollowUpTask.id == body.complete_task_id)
        )
        if task_to_close is None or task_to_close.lead_id != lead.id:
            raise _unprocessable("That follow-up doesn't belong to this lead")
        if not task_svc.can_act_on(user, task_to_close):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "You can't change that follow-up")
        if task_to_close.status != TaskStatus.pending:
            raise _unprocessable("That follow-up is already closed")

    call = CallLog(
        lead_id=lead.id,
        user_id=user.id,
        direction=body.direction,
        outcome=body.outcome,
        duration_sec=body.duration_sec,
        notes=body.notes or None,
        called_at=called_at,
    )
    db.add(call)
    await db.flush()

    label = svc.CALL_LABELS[body.outcome.value]
    lead_svc.add_activity(
        db,
        lead,
        actor=user,
        type="call_logged",
        note=call.notes,
        details={
            "call_id": call.id,
            "outcome": body.outcome.value,
            "direction": body.direction.value,
            "duration_sec": body.duration_sec,
            "connected": body.outcome in svc.CONNECTED_OUTCOMES,
        },
    )

    if task_to_close is not None:
        task_to_close.status = TaskStatus.completed
        task_to_close.completed_at = now
        task_to_close.completed_by_id = user.id
        task_to_close.completion_note = f"Call: {label}" + (f". {call.notes}" if call.notes else "")
        lead_svc.add_activity(
            db,
            lead,
            actor=user,
            type="task_completed",
            note=task_to_close.completion_note,
            details={
                "task_id": task_to_close.id,
                "task_type": task_to_close.task_type.value,
                "was_overdue": task_to_close.due_at < now,
            },
        )

    if body.follow_up_at is not None:
        task = await task_svc.create_follow_up(
            db,
            lead=lead,
            actor=user,
            task_type=body.follow_up_type,
            due_at=body.follow_up_at,
            notes=f"After call: {label}",
            source="call",
        )
        call.follow_up_task_id = task.id

    log_audit(
        db,
        action="call.log",
        entity_type="call",
        entity_id=call.id,
        actor=user,
        details={"lead_id": lead.id, "outcome": body.outcome.value},
        request=request,
    )
    await db.commit()
    await db.refresh(call)
    return svc.to_out(call)
