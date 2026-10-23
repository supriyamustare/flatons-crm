from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select

from app.core.deps import CurrentUser, DbSession, require_role
from app.models.project import Project
from app.models.user import Role, User
from app.schemas.project import ProjectCreate, ProjectOut, ProjectUpdate
from app.services.audit import log_audit

router = APIRouter(prefix="/projects", tags=["projects"])
Admin = Annotated[User, Depends(require_role(Role.admin))]


async def _name_taken(db: DbSession, name: str, exclude_id: int | None = None) -> bool:
    stmt = select(Project.id).where(Project.name.ilike(name))
    if exclude_id is not None:
        stmt = stmt.where(Project.id != exclude_id)
    return await db.scalar(stmt) is not None


@router.get("", response_model=list[ProjectOut])
async def list_projects(
    user: CurrentUser, db: DbSession, include_inactive: bool = False
) -> list[Project]:
    stmt = select(Project).order_by(Project.name)
    if not (include_inactive and user.role == Role.admin):
        stmt = stmt.where(Project.is_active.is_(True))
    return list(await db.scalars(stmt))


@router.post("", response_model=ProjectOut, status_code=status.HTTP_201_CREATED)
async def create_project(
    body: ProjectCreate, request: Request, admin: Admin, db: DbSession
) -> Project:
    if await _name_taken(db, body.name):
        raise HTTPException(status.HTTP_409_CONFLICT, "A project with this name already exists")
    project = Project(name=body.name)
    db.add(project)
    await db.flush()
    log_audit(
        db,
        action="project.create",
        entity_type="project",
        entity_id=project.id,
        actor=admin,
        details={"name": project.name},
        request=request,
    )
    await db.commit()
    await db.refresh(project)
    return project


@router.patch("/{project_id}", response_model=ProjectOut)
async def update_project(
    project_id: int, body: ProjectUpdate, request: Request, admin: Admin, db: DbSession
) -> Project:
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    if body.name is not None and body.name != project.name:
        if await _name_taken(db, body.name, exclude_id=project.id):
            raise HTTPException(status.HTTP_409_CONFLICT, "A project with this name already exists")
        project.name = body.name
    if body.is_active is not None:
        project.is_active = body.is_active
    log_audit(
        db,
        action="project.update",
        entity_type="project",
        entity_id=project.id,
        actor=admin,
        details=body.model_dump(exclude_unset=True),
        request=request,
    )
    await db.commit()
    await db.refresh(project)
    return project
