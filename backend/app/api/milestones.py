from datetime import UTC, date, datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, StringConstraints
from sqlalchemy import func, select

from app.core.deps import DbSession, require_role
from app.models.milestone import MilestoneEvidence, MilestoneStatus, ProjectMilestone
from app.models.project import Project
from app.models.user import POSTSALES_ROLES, Role, User
from app.schemas.common import PlainText
from app.schemas.user import UserBrief
from app.services import demands as svc
from app.services import receipts as files
from app.services.audit import log_audit
from app.services.notifications import notify

router = APIRouter(tags=["milestones"])
Viewer = Annotated[User, Depends(require_role(*POSTSALES_ROLES, Role.manager))]
Reporter = Annotated[User, Depends(require_role(Role.admin, Role.project_manager, Role.site))]
Verifier = Annotated[User, Depends(require_role(Role.admin, Role.crm_manager))]
IST = timezone(timedelta(hours=5, minutes=30))
FOLDER = "milestones"


def today() -> date:
    return datetime.now(UTC).astimezone(IST).date()


class EvidenceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    file_name: str
    file_type: str
    url: str = ""


class MilestoneOut(BaseModel):
    id: int | None
    name: str
    status: MilestoneStatus
    completed_on: date | None = None
    note: str | None = None
    returned_reason: str | None = None
    reported_by: UserBrief | None = None
    reported_at: datetime | None = None
    verified_by: UserBrief | None = None
    verified_at: datetime | None = None
    evidence: list[EvidenceOut] = []
    can_report: bool = False
    can_verify: bool = False


class VerifyOut(BaseModel):
    milestone: MilestoneOut
    cases: int
    demands: int
    ledgers_not_approved: int
    due_date: date


class ReasonIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: Annotated[PlainText, StringConstraints(min_length=3, max_length=500)]


async def _project(db: DbSession, pid: int) -> Project:
    p = await db.get(Project, pid)
    if p is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    return p


async def _out(db: DbSession, m: ProjectMilestone | None, name: str, user: User) -> MilestoneOut:
    if m is None:
        return MilestoneOut(
            id=None,
            name=name,
            status=MilestoneStatus.planned,
            can_report=user.role in (Role.admin, Role.project_manager, Role.site),
        )
    ids = {x for x in (m.reported_by_id, m.verified_by_id) if x}
    users = {u.id: u for u in await db.scalars(select(User).where(User.id.in_(ids)))} if ids else {}
    brief = lambda uid: UserBrief.model_validate(users[uid]) if uid in users else None  # noqa: E731
    return MilestoneOut(
        id=m.id,
        name=m.name,
        status=m.status,
        completed_on=m.completed_on,
        note=m.note,
        returned_reason=m.returned_reason,
        reported_by=brief(m.reported_by_id),
        reported_at=m.reported_at,
        verified_by=brief(m.verified_by_id),
        verified_at=m.verified_at,
        evidence=[
            EvidenceOut(
                id=e.id,
                file_name=e.file_name,
                file_type=e.file_type,
                url=f"/api/milestones/evidence/{e.id}/file",
            )
            for e in m.evidence
        ],
        can_report=user.role in (Role.admin, Role.project_manager, Role.site)
        and m.status != MilestoneStatus.verified,
        can_verify=user.role in (Role.admin, Role.crm_manager)
        and m.status == MilestoneStatus.reported
        and m.reported_by_id != user.id,
    )


@router.get("/projects/{project_id}/milestones", response_model=list[MilestoneOut])
async def list_milestones(project_id: int, user: Viewer, db: DbSession) -> list[MilestoneOut]:
    project = await _project(db, project_id)
    rows = {
        m.name.strip().lower(): m
        for m in await db.scalars(
            select(ProjectMilestone).where(ProjectMilestone.project_id == project_id)
        )
    }
    names = svc.milestone_names(project)
    names += [m.name for k, m in rows.items() if k not in {n.strip().lower() for n in names}]
    return [await _out(db, rows.get(n.strip().lower()), n, user) for n in names]


@router.post("/projects/{project_id}/milestones/report", response_model=MilestoneOut)
async def report(
    project_id: int,
    request: Request,
    user: Reporter,
    db: DbSession,
    name: Annotated[str, Form(min_length=1, max_length=120)],
    completed_on: Annotated[date, Form()],
    files_in: Annotated[list[UploadFile], File(alias="files")],
    note: Annotated[str | None, Form(max_length=2000)] = None,
) -> MilestoneOut:
    """Report a milestone complete, with at least one photo or certificate as evidence."""
    project = await _project(db, project_id)
    if name.strip().lower() not in {n.strip().lower() for n in svc.milestone_names(project)}:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "That isn't one of this project's payment stages"
        )
    if completed_on > today():
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "The completion date can't be in the future"
        )
    if not files_in or len(files_in) > 10:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "Attach between 1 and 10 evidence files"
        )
    if note and ("<" in note or ">" in note):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "The note can't contain < or >")
    m = await db.scalar(
        select(ProjectMilestone).where(
            ProjectMilestone.project_id == project_id,
            func.lower(ProjectMilestone.name) == name.strip().lower(),
        )
    )
    if m is not None and m.status == MilestoneStatus.verified:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "This milestone is already verified"
        )
    stored = []
    try:
        for f in files_in:
            stored.append(
                await files.save_receipt(f, folder=FOLDER, max_mb=15, what="Evidence files")
            )
    except files.ReceiptError as exc:
        for path, _, _ in stored:
            files.delete_receipt(path, FOLDER)
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
    if m is None:
        m = ProjectMilestone(project_id=project_id, name=name.strip())
        db.add(m)
    m.status, m.completed_on, m.note, m.returned_reason = (
        MilestoneStatus.reported,
        completed_on,
        (note or "").strip() or None,
        None,
    )
    m.reported_by_id, m.reported_at = user.id, datetime.now(UTC)
    m.evidence = [
        *m.evidence,
        *[
            MilestoneEvidence(file_path=p, file_name=n, file_type=t, uploaded_by_id=user.id)
            for p, n, t in stored
        ],
    ]
    await db.flush()
    log_audit(
        db,
        action="milestone.reported",
        entity_type="project_milestone",
        entity_id=m.id,
        actor=user,
        details={
            "project_id": project_id,
            "name": m.name,
            "completed_on": completed_on.isoformat(),
        },
        request=request,
    )
    for uid in await db.scalars(
        select(User.id).where(
            User.is_active.is_(True), User.role == Role.crm_manager, User.id != user.id
        )
    ):
        notify(
            db,
            user_id=uid,
            type="milestone_reported",
            title=f"Milestone to verify: {project.name}, {m.name}",
            body=f"Reported complete on {completed_on.isoformat()}",
            link=f"/projects/{project_id}#milestones",
        )
    await db.commit()
    await db.refresh(m)
    return await _out(db, m, m.name, user)


async def _milestone(db: DbSession, project_id: int, mid: int) -> ProjectMilestone:
    m = await db.get(ProjectMilestone, mid)
    if m is None or m.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Milestone not found")
    return m


@router.post("/projects/{project_id}/milestones/{mid}/verify", response_model=VerifyOut)
async def verify(
    project_id: int, mid: int, request: Request, user: Verifier, db: DbSession
) -> VerifyOut:
    project = await _project(db, project_id)
    m = await _milestone(db, project_id, mid)
    if m.status != MilestoneStatus.reported:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "Only a reported milestone can be verified"
        )
    if m.reported_by_id == user.id:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "The person who reported a milestone can't verify it"
        )
    t = today()
    m.status, m.verified_by_id, m.verified_at = MilestoneStatus.verified, user.id, datetime.now(UTC)
    summary = await svc.apply_milestone(db, m, project, user, t)
    log_audit(
        db,
        action="milestone.verified",
        entity_type="project_milestone",
        entity_id=m.id,
        actor=user,
        details={"project_id": project_id, "name": m.name, **summary},
        request=request,
    )
    if summary["demands"]:
        for uid in await db.scalars(
            select(User.id).where(User.is_active.is_(True), User.role == Role.finance)
        ):
            notify(
                db,
                user_id=uid,
                type="demands_drafted",
                title=f"{summary['demands']} demands to prepare: {project.name}, {m.name}",
                body="Milestone verified; draft demands are ready to check and submit",
                link="/post-sales",
            )
    await db.commit()
    await db.refresh(m)
    return VerifyOut(
        milestone=await _out(db, m, m.name, user),
        due_date=t + timedelta(days=svc.due_days(project)),
        **summary,
    )


@router.post("/projects/{project_id}/milestones/{mid}/return", response_model=MilestoneOut)
async def return_milestone(
    project_id: int, mid: int, body: ReasonIn, request: Request, user: Verifier, db: DbSession
) -> MilestoneOut:
    m = await _milestone(db, project_id, mid)
    if m.status != MilestoneStatus.reported:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "Only a reported milestone can be returned"
        )
    m.status, m.returned_reason = MilestoneStatus.planned, body.reason
    log_audit(
        db,
        action="milestone.returned",
        entity_type="project_milestone",
        entity_id=m.id,
        actor=user,
        details={"reason": body.reason},
        request=request,
    )
    if m.reported_by_id:
        notify(
            db,
            user_id=m.reported_by_id,
            type="milestone_returned",
            title=f"Milestone returned: {m.name}",
            body=body.reason,
            link=f"/projects/{project_id}#milestones",
        )
    await db.commit()
    await db.refresh(m)
    return await _out(db, m, m.name, user)


@router.get("/milestones/evidence/{eid}/file")
async def evidence_file(eid: int, _: Viewer, db: DbSession) -> FileResponse:
    e = await db.get(MilestoneEvidence, eid)
    if e is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found")
    path = files.receipt_file(e.file_path, FOLDER)
    if not path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "The file is missing")
    return FileResponse(
        path,
        media_type=e.file_type,
        headers={"Content-Disposition": f'inline; filename="{e.file_name}"'},
    )
