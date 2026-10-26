from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.deps import CurrentUser, DbSession, require_role
from app.models.inventory import Building
from app.models.project import Developer, Project, ProjectType
from app.models.user import Role, User
from app.schemas.inventory import BuildingCreate, BuildingOut, Inventory
from app.schemas.project import (
    DeveloperCreate,
    DeveloperOut,
    ProjectCreate,
    ProjectOut,
    ProjectUpdate,
    ProjectWithCounts,
)
from app.services import inventory as inv
from app.services.audit import log_audit

router = APIRouter(tags=["projects"])
Admin = Annotated[User, Depends(require_role(Role.admin))]


def _conflict(msg: str) -> HTTPException:
    return HTTPException(status.HTTP_409_CONFLICT, msg)


def _unprocessable(msg: str) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, msg)


async def _name_taken(db: DbSession, model, name: str, exclude_id: int | None = None) -> bool:
    stmt = select(model.id).where(model.name.ilike(name))
    if exclude_id is not None:
        stmt = stmt.where(model.id != exclude_id)
    return await db.scalar(stmt) is not None


async def _resolve_developer(
    db: DbSession, developer_id: int | None, developer_name: str | None
) -> Developer | None:
    if developer_id is not None:
        dev = await db.get(Developer, developer_id)
        if dev is None:
            raise _unprocessable("That developer doesn't exist")
        return dev
    if developer_name:
        existing = await db.scalar(select(Developer).where(Developer.name.ilike(developer_name)))
        if existing:
            return existing
        dev = Developer(name=developer_name)
        db.add(dev)
        await db.flush()
        return dev
    return None


async def get_project_or_404(db: DbSession, project_id: int) -> Project:
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    return project


# ---- Developers ------------------------------------------------------------


@router.get("/developers", response_model=list[DeveloperOut])
async def list_developers(_: CurrentUser, db: DbSession) -> list[Developer]:
    return list(await db.scalars(select(Developer).order_by(Developer.name)))


@router.post("/developers", response_model=DeveloperOut, status_code=status.HTTP_201_CREATED)
async def create_developer(
    body: DeveloperCreate, request: Request, admin: Admin, db: DbSession
) -> Developer:
    if await _name_taken(db, Developer, body.name):
        raise _conflict("A developer with this name already exists")
    dev = Developer(name=body.name)
    db.add(dev)
    await db.flush()
    log_audit(
        db,
        action="developer.create",
        entity_type="developer",
        entity_id=dev.id,
        actor=admin,
        details={"name": dev.name},
        request=request,
    )
    await db.commit()
    await db.refresh(dev)
    return dev


# ---- Projects --------------------------------------------------------------


@router.get("/projects", response_model=list[ProjectWithCounts])
async def list_projects(
    user: CurrentUser, db: DbSession, include_inactive: bool = False
) -> list[ProjectWithCounts]:
    stmt = select(Project).order_by(Project.name)
    if not (include_inactive and user.role == Role.admin):
        stmt = stmt.where(Project.is_active.is_(True))
    projects = list(await db.scalars(stmt))
    counts = await inv.project_unit_counts(db, [p.id for p in projects])
    return [
        ProjectWithCounts(**ProjectOut.model_validate(p).model_dump(), units=counts.get(p.id, {}))
        for p in projects
    ]


@router.post("/projects", response_model=ProjectOut, status_code=status.HTTP_201_CREATED)
async def create_project(
    body: ProjectCreate, request: Request, admin: Admin, db: DbSession
) -> Project:
    if await _name_taken(db, Project, body.name):
        raise _conflict("A project with this name already exists")
    developer = await _resolve_developer(db, body.developer_id, body.developer_name)
    project = Project(
        name=body.name,
        project_type=body.project_type,
        status=body.status,
        developer_id=developer.id if developer else None,
        location=body.location,
        description=body.description,
    )
    db.add(project)
    await db.flush()
    log_audit(
        db,
        action="project.create",
        entity_type="project",
        entity_id=project.id,
        actor=admin,
        details={"name": project.name, "type": project.project_type.value},
        request=request,
    )
    await db.commit()
    await db.refresh(project)
    return project


@router.get("/projects/{project_id}", response_model=ProjectOut)
async def get_project(project_id: int, _: CurrentUser, db: DbSession) -> Project:
    return await get_project_or_404(db, project_id)


@router.patch("/projects/{project_id}", response_model=ProjectOut)
async def update_project(
    project_id: int, body: ProjectUpdate, request: Request, admin: Admin, db: DbSession
) -> Project:
    project = await get_project_or_404(db, project_id)
    changes = body.model_dump(exclude_unset=True)
    if "name" in changes and changes["name"] != project.name:
        if await _name_taken(db, Project, changes["name"], exclude_id=project.id):
            raise _conflict("A project with this name already exists")

    new_type = changes.get("project_type", project.project_type)
    if "developer_id" in changes or "developer_name" in changes or "project_type" in changes:
        dev = await _resolve_developer(
            db, changes.get("developer_id"), changes.get("developer_name")
        )
        if new_type == ProjectType.resale:
            if dev is not None:
                raise _unprocessable("Resale listings don't have a developer")
            project.developer_id = None
        else:
            dev_id = dev.id if dev else project.developer_id
            if dev_id is None:
                raise _unprocessable("A developer project needs its developer")
            project.developer_id = dev_id
        project.project_type = new_type
    for field in ("name", "is_active", "status", "location", "description"):
        if field in changes:
            setattr(project, field, changes[field])

    log_audit(
        db,
        action="project.update",
        entity_type="project",
        entity_id=project.id,
        actor=admin,
        details={k: str(v) for k, v in changes.items()},
        request=request,
    )
    try:
        await db.commit()
    except IntegrityError:
        raise _unprocessable(
            "A developer project needs its developer; a resale listing can't have one"
        ) from None
    await db.refresh(project)
    return project


@router.get("/projects/{project_id}/inventory", response_model=Inventory)
async def project_inventory(project_id: int, _: CurrentUser, db: DbSession) -> Inventory:
    """Full building -> floor -> unit tree (top floor first) plus resale listings and counts."""
    return await inv.build_inventory(db, await get_project_or_404(db, project_id))


@router.post(
    "/projects/{project_id}/buildings",
    response_model=BuildingOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_building(
    project_id: int, body: BuildingCreate, request: Request, admin: Admin, db: DbSession
) -> Building:
    project = await get_project_or_404(db, project_id)
    if project.project_type == ProjectType.resale:
        raise _unprocessable("Resale listings don't have buildings; add units directly")
    if await db.scalar(
        select(Building.id).where(Building.project_id == project.id, Building.name.ilike(body.name))
    ):
        raise _conflict(f"{project.name} already has a building called {body.name}")
    building = Building(project_id=project.id, name=body.name, sort_order=body.sort_order)
    db.add(building)
    await db.flush()
    log_audit(
        db,
        action="building.create",
        entity_type="building",
        entity_id=building.id,
        actor=admin,
        details={"project_id": project.id, "name": building.name},
        request=request,
    )
    await db.commit()
    await db.refresh(building)
    return building
