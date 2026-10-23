"""Audit logging. Entries are added to the caller's session and committed with the action,
so an action and its audit record are saved together or not at all."""

from typing import Any

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog
from app.models.user import User


def client_ip(request: Request | None) -> str | None:
    if request is None:
        return None
    # Nginx sets X-Real-IP; the API itself only listens on localhost behind Nginx.
    return request.headers.get("x-real-ip") or (request.client.host if request.client else None)


def log_audit(
    db: AsyncSession,
    *,
    action: str,
    entity_type: str,
    entity_id: int | str | None = None,
    actor: User | None = None,
    details: dict[str, Any] | None = None,
    request: Request | None = None,
) -> AuditLog:
    entry = AuditLog(
        actor_id=actor.id if actor else None,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id is not None else None,
        details=details,
        ip_address=client_ip(request),
    )
    db.add(entry)
    return entry
