from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.core.deps import CurrentUser, DbSession
from app.models.notification import Notification
from app.schemas.notification import NotificationList, NotificationOut
from app.services import notifications as svc

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", response_model=NotificationList)
async def list_notifications(user: CurrentUser, db: DbSession) -> NotificationList:
    items, unread = await svc.list_for_user(db, user)
    return NotificationList(
        items=[NotificationOut.model_validate(n) for n in items], unread_count=unread
    )


@router.patch("/{notification_id}/read", response_model=NotificationOut)
async def mark_read(notification_id: int, user: CurrentUser, db: DbSession) -> Notification:
    n = await db.scalar(
        select(Notification).where(
            Notification.id == notification_id, Notification.user_id == user.id
        )
    )
    if n is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Notification not found")
    if n.read_at is None:
        n.read_at = datetime.now(UTC)
        await db.commit()
        await db.refresh(n)
    return n


@router.post("/read-all", status_code=status.HTTP_204_NO_CONTENT)
async def mark_all_read(user: CurrentUser, db: DbSession) -> None:
    await svc.mark_all_read(db, user)
    await db.commit()
