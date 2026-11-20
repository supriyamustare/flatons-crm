from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, StringConstraints
from sqlalchemy import select

from app.core.deps import DbSession, require_role
from app.models.milestone import ProjectMilestone
from app.models.project import Project
from app.models.project_update import (
    ProjectUpdate,
    ProjectUpdateCorrection,
    ProjectUpdatePhoto,
    UpdateStatus,
)
from app.models.user import POSTSALES_ROLES, Role, User
from app.schemas.common import PlainText
from app.services import receipts as files
from app.services.audit import log_audit
from app.services.notifications import notify

router = APIRouter(tags=["project updates"])
Viewer = Annotated[User, Depends(require_role(*POSTSALES_ROLES, Role.manager))]
AUTHORS = (Role.admin, Role.crm_manager, Role.project_manager, Role.postsales_exec)
APPROVERS = (Role.admin, Role.crm_manager)
Author = Annotated[User, Depends(require_role(*AUTHORS))]
Approver = Annotated[User, Depends(require_role(*APPROVERS))]
FOLDER = "project_updates"


class ReasonIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: Annotated[PlainText, StringConstraints(min_length=3, max_length=500)]


class EditIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: Annotated[PlainText, StringConstraints(min_length=3, max_length=200)]
    body: Annotated[PlainText, StringConstraints(min_length=10, max_length=5000)]


class CorrectIn(EditIn):
    reason: Annotated[PlainText, StringConstraints(min_length=3, max_length=500)]


def _clean(text: str) -> str:
    if "<" in text or ">" in text:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Text can't contain < or >")
    return text.strip()


async def _project(db: DbSession, pid: int) -> Project:
    p = await db.get(Project, pid)
    if p is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    return p


async def listing(db: DbSession, project_id: int, user: User) -> list[dict]:
    rows = list(
        await db.scalars(
            select(ProjectUpdate)
            .where(ProjectUpdate.project_id == project_id)
            .order_by(ProjectUpdate.id.desc())
        )
    )
    ids = {x for u in rows for x in (u.author_id, u.published_by_id) if x} | {
        c.by_id for u in rows for c in u.corrections if c.by_id
    }
    users = (
        {x.id: x.full_name for x in await db.scalars(select(User).where(User.id.in_(ids)))}
        if ids
        else {}
    )
    names = {
        m.id: m.name
        for m in await db.scalars(
            select(ProjectMilestone).where(ProjectMilestone.project_id == project_id)
        )
    }
    out = []
    for u in rows:
        mine = u.author_id == user.id
        out.append(
            {
                "id": u.id,
                "title": u.title,
                "body": u.body,
                "status": u.status.value,
                "milestone": names.get(u.milestone_id),
                "author": users.get(u.author_id),
                "created_at": u.created_at,
                "published_at": u.published_at,
                "published_by": users.get(u.published_by_id),
                "returned_reason": u.returned_reason,
                "photos": [
                    {
                        "id": p.id,
                        "file_name": p.file_name,
                        "url": f"/api/project-updates/photos/{p.id}",
                    }
                    for p in u.photos
                ],
                "corrections": [
                    {
                        "at": c.at,
                        "by": users.get(c.by_id),
                        "reason": c.reason,
                        "previous_title": c.previous_title,
                        "previous_body": c.previous_body,
                    }
                    for c in u.corrections
                ],
                "can_edit": u.status != UpdateStatus.published
                and user.role in AUTHORS
                and (mine or user.role in APPROVERS),
                "can_publish": u.status == UpdateStatus.pending_approval
                and user.role in APPROVERS
                and not mine,
                "can_correct": u.status == UpdateStatus.published and user.role in APPROVERS,
            }
        )
    return out


async def _update(db: DbSession, uid: int) -> ProjectUpdate:
    u = await db.get(ProjectUpdate, uid)
    if u is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Update not found")
    return u


def _log(
    db: DbSession,
    user: User,
    action: str,
    u: ProjectUpdate,
    request: Request,
    extra: dict | None = None,
) -> None:
    log_audit(
        db,
        action=f"project_update.{action}",
        entity_type="project_update",
        entity_id=u.id,
        actor=user,
        details={"title": u.title, **(extra or {})},
        request=request,
    )


@router.get("/projects/{project_id}/updates")
async def list_updates(project_id: int, user: Viewer, db: DbSession) -> list[dict]:
    await _project(db, project_id)
    return await listing(db, project_id, user)


@router.post("/projects/{project_id}/updates", status_code=status.HTTP_201_CREATED)
async def write(
    project_id: int,
    request: Request,
    user: Author,
    db: DbSession,
    title: Annotated[str, Form(min_length=3, max_length=200)],
    body: Annotated[str, Form(min_length=10, max_length=5000)],
    milestone_id: Annotated[int | None, Form()] = None,
    photos: Annotated[list[UploadFile] | None, File()] = None,
) -> list[dict]:
    """A customer-facing update. It waits for approval by someone else before customers can see it."""
    project = await _project(db, project_id)
    if milestone_id is not None:
        m = await db.get(ProjectMilestone, milestone_id)
        if m is None or m.project_id != project_id:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, "That milestone isn't in this project"
            )
    if photos and len(photos) > 8:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Attach up to 8 photos")
    stored = []
    try:
        for f in photos or []:
            stored.append(await files.save_receipt(f, folder=FOLDER, max_mb=10, what="Photos"))
    except files.ReceiptError as exc:
        for path, _, _ in stored:
            files.delete_receipt(path, FOLDER)
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
    u = ProjectUpdate(
        project_id=project_id,
        milestone_id=milestone_id,
        title=_clean(title),
        body=_clean(body),
        author_id=user.id,
        photos=[ProjectUpdatePhoto(file_path=p, file_name=n, file_type=t) for p, n, t in stored],
    )
    db.add(u)
    await db.flush()
    _log(db, user, "written", u, request)
    for uid in await db.scalars(
        select(User.id).where(
            User.is_active.is_(True), User.role == Role.crm_manager, User.id != user.id
        )
    ):
        notify(
            db,
            user_id=uid,
            type="project_update_approval",
            title=f"Customer update to approve: {project.name}",
            body=u.title,
            link=f"/projects/{project_id}#updates",
        )
    await db.commit()
    return await listing(db, project_id, user)


@router.put("/project-updates/{uid}")
async def edit(uid: int, body: EditIn, request: Request, user: Author, db: DbSession) -> list[dict]:
    u = await _update(db, uid)
    if u.status == UpdateStatus.published:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "A published update is corrected, not edited"
        )
    if u.author_id != user.id and user.role not in APPROVERS:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Only the author or a CRM manager can edit this update"
        )
    u.title, u.body, u.status, u.returned_reason = (
        _clean(body.title),
        _clean(body.body),
        UpdateStatus.pending_approval,
        None,
    )
    _log(db, user, "edited", u, request)
    await db.commit()
    return await listing(db, u.project_id, user)


@router.post("/project-updates/{uid}/publish")
async def publish(uid: int, request: Request, user: Approver, db: DbSession) -> list[dict]:
    u = await _update(db, uid)
    if u.status != UpdateStatus.pending_approval:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Only an update waiting for approval can be published",
        )
    if u.author_id == user.id:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Someone other than the author must approve and publish it"
        )
    u.status, u.published_by_id, u.published_at = UpdateStatus.published, user.id, datetime.now(UTC)
    _log(db, user, "published", u, request)
    await db.commit()
    return await listing(db, u.project_id, user)


@router.post("/project-updates/{uid}/return")
async def return_update(
    uid: int, body: ReasonIn, request: Request, user: Approver, db: DbSession
) -> list[dict]:
    u = await _update(db, uid)
    if u.status != UpdateStatus.pending_approval:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Only an update waiting for approval can be returned",
        )
    u.status, u.returned_reason = UpdateStatus.draft, body.reason
    _log(db, user, "returned", u, request, {"reason": body.reason})
    if u.author_id:
        notify(
            db,
            user_id=u.author_id,
            type="project_update_returned",
            title=f"Update returned: {u.title}",
            body=body.reason,
            link=f"/projects/{u.project_id}#updates",
        )
    await db.commit()
    return await listing(db, u.project_id, user)


@router.post("/project-updates/{uid}/correct")
async def correct(
    uid: int, body: CorrectIn, request: Request, user: Approver, db: DbSession
) -> list[dict]:
    """Correct a published update: the earlier wording stays in its history with who, when and why."""
    u = await _update(db, uid)
    if u.status != UpdateStatus.published:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "Only a published update can be corrected"
        )
    u.corrections.append(
        ProjectUpdateCorrection(
            previous_title=u.title, previous_body=u.body, reason=body.reason, by_id=user.id
        )
    )
    u.title, u.body = _clean(body.title), _clean(body.body)
    _log(db, user, "corrected", u, request, {"reason": body.reason})
    await db.commit()
    return await listing(db, u.project_id, user)


@router.get("/project-updates/photos/{pid}")
async def photo(pid: int, _: Viewer, db: DbSession) -> FileResponse:
    p = await db.get(ProjectUpdatePhoto, pid)
    if p is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Photo not found")
    path = files.receipt_file(p.file_path, FOLDER)
    if not path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "The file is missing")
    return FileResponse(
        path,
        media_type=p.file_type,
        headers={"Content-Disposition": f'inline; filename="{p.file_name}"'},
    )
