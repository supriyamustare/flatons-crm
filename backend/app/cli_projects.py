"""Load the real projects (Habitat, Optimids) from app/data/projects_seed.json.

Safe to run again: it creates what's missing and fills only empty fields. It never changes a unit's
price, a booked or held unit, or anything an admin has already entered."""

import json
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.inventory import Building, Floor, Unit, UnitStatus, UnitType
from app.models.project import Developer, Project, ProjectStatus, ProjectType

SEED = Path(__file__).parent / "data" / "projects_seed.json"
PLACEHOLDER_DEVELOPER = "Developer to be confirmed"


async def _developer(db: AsyncSession, name: str | None) -> Developer:
    name = name or PLACEHOLDER_DEVELOPER
    dev = await db.scalar(select(Developer).where(Developer.name.ilike(name)))
    if dev is None:
        dev = Developer(name=name)
        db.add(dev)
        await db.flush()
    return dev


async def load_projects(db: AsyncSession) -> dict[str, int]:
    data = json.loads(SEED.read_text())
    counts = {"projects_created": 0, "projects_updated": 0, "units_created": 0, "units_filled": 0}
    for p in data["projects"]:
        dev = await _developer(db, p["developer"])
        project = await db.scalar(select(Project).where(Project.name.ilike(p["name"])))
        if project is None:
            project = Project(
                name=p["name"],
                project_type=ProjectType(p["project_type"]),
                developer_id=dev.id,
                status=ProjectStatus(p["status"]),
                location=p["location"],
                description=p["description"],
                commission_pct=Decimal(str(p["commission_pct"]))
                if p["commission_pct"] is not None
                else None,
                cost_sheet=p["cost_sheet"],
                is_active=True,
            )
            db.add(project)
            await db.flush()
            counts["projects_created"] += 1
        else:
            changed = False
            for field in ("location", "description", "cost_sheet"):
                if getattr(project, field) in (None, "") and p[field]:
                    setattr(project, field, p[field])
                    changed = True
            if project.commission_pct is None and p["commission_pct"] is not None:
                project.commission_pct = Decimal(str(p["commission_pct"]))
                changed = True
            counts["projects_updated"] += changed
        if not p["units"]:
            continue
        building = await db.scalar(
            select(Building).where(
                Building.project_id == project.id, Building.name == p["building"]
            )
        )
        if building is None:
            building = Building(project_id=project.id, name=p["building"], sort_order=0)
            db.add(building)
            await db.flush()
        floors = {
            f.number: f
            for f in await db.scalars(select(Floor).where(Floor.building_id == building.id))
        }
        existing = {
            u.unit_no: u
            for u in await db.scalars(select(Unit).where(Unit.project_id == project.id))
        }
        for u in p["units"]:
            if u["floor"] not in floors:
                floors[u["floor"]] = Floor(building_id=building.id, number=u["floor"])
                db.add(floors[u["floor"]])
                await db.flush()
            note = f"{u['use']} ({u['source_name'].title()}), lease factor {u['lease_factor']}"
            unit = existing.get(u["unit_no"])
            if unit is None:
                db.add(
                    Unit(
                        project_id=project.id,
                        building_id=building.id,
                        floor_id=floors[u["floor"]].id,
                        unit_no=u["unit_no"],
                        unit_type=UnitType(u["unit_type"]),
                        carpet_sqft=Decimal(str(u["carpet_sqft"])),
                        builtup_sqft=Decimal(str(u["saleable_sqft"])),
                        status=UnitStatus.available,
                        address_note=note,
                    )
                )
                counts["units_created"] += 1
            elif unit.status == UnitStatus.available and (
                unit.carpet_sqft is None or unit.builtup_sqft is None
            ):
                unit.carpet_sqft = unit.carpet_sqft or Decimal(str(u["carpet_sqft"]))
                unit.builtup_sqft = unit.builtup_sqft or Decimal(str(u["saleable_sqft"]))
                counts["units_filled"] += 1
    return counts
