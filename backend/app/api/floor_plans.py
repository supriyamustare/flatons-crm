from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy import and_, or_, select

from app.core.deps import DbSession, require_role
from app.models.floor_plan import FloorPlan
from app.models.inventory import Building, Floor, Unit, UnitType
from app.models.project import Project
from app.models.user import Role, User
from app.services import receipts as files
from app.services.audit import log_audit

router = APIRouter(tags=["floor plans"])
Viewer = Annotated[User, Depends(require_role(Role.admin, Role.manager, Role.executive, Role.docs))]
Manager = Annotated[User, Depends(require_role(Role.admin, Role.manager))]
FOLDER = "floor_plans"


class FloorPlanOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    project_id: int
    floor_id: int | None
    floor_number: int | None = None
    unit_type: UnitType | None
    title: str
    file_name: str
    file_type: str
    url: str = ""  # where to view it (signed-in staff only)
    applies_to: str = ""  # "Whole project" / "Floor 2" / "2 BHK units"


TYPE_NAMES = {
    "1bhk": "1 BHK",
    "2bhk": "2 BHK",
    "3bhk": "3 BHK",
    "4bhk": "4 BHK",
    "studio": "Studio",
    "shop": "Shop",
    "office": "Office",
}


async def _out(db: DbSession, fp: FloorPlan) -> FloorPlanOut:
    o = FloorPlanOut.model_validate(fp)
    o.url = f"/api/floor-plans/{fp.id}/file"
    if fp.floor_id:
        floor = await db.get(Floor, fp.floor_id)
        o.floor_number = floor.number if floor else None
        o.applies_to = "Ground floor" if o.floor_number == 0 else f"Floor {o.floor_number}"
    elif fp.unit_type:
        o.applies_to = f"{TYPE_NAMES.get(fp.unit_type.value, fp.unit_type.value)} units"
    else:
        o.applies_to = "Whole project"
    return o


@router.get("/projects/{project_id}/floor-plans", response_model=list[FloorPlanOut])
async def list_plans(project_id: int, _: Viewer, db: DbSession) -> list[FloorPlanOut]:
    plans = await db.scalars(
        select(FloorPlan)
        .where(FloorPlan.project_id == project_id)
        .order_by(FloorPlan.created_at.desc(), FloorPlan.id.desc())
    )
    return [await _out(db, p) for p in plans]


@router.post(
    "/projects/{project_id}/floor-plans",
    response_model=FloorPlanOut,
    status_code=status.HTTP_201_CREATED,
)
async def upload_plan(
    project_id: int,
    request: Request,
    user: Manager,
    db: DbSession,
    title: Annotated[str, Form(min_length=1, max_length=150)],
    file: Annotated[UploadFile, File()],
    floor_id: Annotated[int | None, Form()] = None,
    unit_type: Annotated[UnitType | None, Form()] = None,
) -> FloorPlanOut:
    """PDF, JPG or PNG up to 15 MB, for the whole project, one floor, or one unit type (not both)."""
    if await db.get(Project, project_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    if "<" in title or ">" in title:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "The title can't contain < or >")
    if floor_id and unit_type:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "Choose a floor or a unit type, not both"
        )
    if floor_id:
        floor = await db.get(Floor, floor_id)
        building = await db.get(Building, floor.building_id) if floor else None
        if building is None or building.project_id != project_id:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, "That floor isn't in this project"
            )
    try:
        stored, name, mime = await files.save_receipt(
            file, folder=FOLDER, max_mb=15, what="Floor plans"
        )
    except files.ReceiptError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
    fp = FloorPlan(
        project_id=project_id,
        floor_id=floor_id,
        unit_type=unit_type,
        title=title.strip(),
        file_path=stored,
        file_name=name,
        file_type=mime,
        uploaded_by_id=user.id,
    )
    db.add(fp)
    await db.flush()
    log_audit(
        db,
        action="floor_plan.upload",
        entity_type="floor_plan",
        entity_id=fp.id,
        actor=user,
        details={"project_id": project_id, "title": fp.title},
        request=request,
    )
    await db.commit()
    await db.refresh(fp)
    return await _out(db, fp)


async def _plan(db: DbSession, plan_id: int) -> FloorPlan:
    fp = await db.get(FloorPlan, plan_id)
    if fp is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Floor plan not found")
    return fp


@router.get("/floor-plans/{plan_id}/file")
async def plan_file(plan_id: int, _: Viewer, db: DbSession) -> FileResponse:
    fp = await _plan(db, plan_id)
    path = files.receipt_file(fp.file_path, FOLDER)
    if not path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "The floor plan file is missing")
    # Shown in the browser (not downloaded) so it can be viewed and printed
    return FileResponse(
        path,
        media_type=fp.file_type,
        headers={
            "Content-Disposition": f'inline; filename="{fp.file_name}"',
            "Cache-Control": "private, max-age=300",
        },
    )


@router.delete("/floor-plans/{plan_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_plan(plan_id: int, request: Request, user: Manager, db: DbSession) -> None:
    fp = await _plan(db, plan_id)
    stored = fp.file_path
    log_audit(
        db,
        action="floor_plan.delete",
        entity_type="floor_plan",
        entity_id=fp.id,
        actor=user,
        details={"title": fp.title, "project_id": fp.project_id},
        request=request,
    )
    await db.delete(fp)
    await db.commit()
    files.delete_receipt(stored, FOLDER)


@router.get("/units/{unit_id}/floor-plans", response_model=list[FloorPlanOut])
async def unit_plans(unit_id: int, _: Viewer, db: DbSession) -> list[FloorPlanOut]:
    """Plans for this unit's floor and its unit type; if none, the project-wide plans."""
    unit = await db.get(Unit, unit_id)
    if unit is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unit not found")
    specific = list(
        await db.scalars(
            select(FloorPlan)
            .where(
                FloorPlan.project_id == unit.project_id,
                or_(
                    and_(FloorPlan.floor_id.is_not(None), FloorPlan.floor_id == unit.floor_id),
                    FloorPlan.unit_type == unit.unit_type,
                ),
            )
            .order_by(FloorPlan.floor_id.is_(None), FloorPlan.created_at.desc())
        )
    )
    plans = specific or list(
        await db.scalars(
            select(FloorPlan)
            .where(
                FloorPlan.project_id == unit.project_id,
                FloorPlan.floor_id.is_(None),
                FloorPlan.unit_type.is_(None),
            )
            .order_by(FloorPlan.created_at.desc())
        )
    )
    return [await _out(db, p) for p in plans]
