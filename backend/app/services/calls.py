from datetime import datetime, time, timedelta

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.call import CONNECTED_OUTCOMES, CallLog
from app.models.user import User
from app.schemas.call import CallOut, CallQuery
from app.services.leads import IST, MANAGERS

CALL_LABELS = {
    "interested": "Interested",
    "callback": "Call back later",
    "not_interested": "Not interested",
    "no_answer": "No answer",
    "busy": "Busy",
    "unreachable": "Switched off / unreachable",
    "wrong_number": "Wrong number",
}


def visible_calls(user: User) -> Select[tuple[CallLog]]:
    """Executives see the calls they made; managers and admins see everyone's."""
    stmt = select(CallLog)
    if user.role not in MANAGERS:
        stmt = stmt.where(CallLog.user_id == user.id)
    return stmt


def to_out(call: CallLog) -> CallOut:
    out = CallOut.model_validate(call)
    out.connected = call.outcome in CONNECTED_OUTCOMES
    return out


async def search_calls(
    db: AsyncSession, user: User, q: CallQuery
) -> tuple[list[CallLog], int, int]:
    stmt = visible_calls(user)
    if q.mine:
        stmt = stmt.where(CallLog.user_id == user.id)
    elif q.user_id is not None and user.role in MANAGERS:
        stmt = stmt.where(CallLog.user_id == q.user_id)
    if q.outcome is not None:
        stmt = stmt.where(CallLog.outcome == q.outcome)
    if q.lead_id is not None:
        stmt = stmt.where(CallLog.lead_id == q.lead_id)
    if q.date_from:
        stmt = stmt.where(CallLog.called_at >= datetime.combine(q.date_from, time.min, IST))
    if q.date_to:
        stmt = stmt.where(
            CallLog.called_at < datetime.combine(q.date_to + timedelta(days=1), time.min, IST)
        )

    sub = stmt.subquery()
    row = (
        await db.execute(
            select(
                func.count(),
                func.count().filter(sub.c.outcome.in_([o.value for o in CONNECTED_OUTCOMES])),
            ).select_from(sub)
        )
    ).one()
    items = await db.scalars(
        stmt.order_by(CallLog.called_at.desc(), CallLog.id.desc())
        .offset((q.page - 1) * q.page_size)
        .limit(q.page_size)
    )
    return list(items), row[0], row[1]
