import calendar
from datetime import UTC, date, datetime, timedelta, timezone
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy import func, select

from app.core.deps import DbSession, require_role
from app.models.aftersales import Defect, DefectFile, FacilityHandover, WarrantyItem
from app.models.milestone import MilestoneStatus, ProjectMilestone
from app.models.possession import PossessionFile
from app.models.postsales import PostSalesCase
from app.models.project import Project
from app.models.user import POSTSALES_ROLES, Role, User
from app.schemas.common import PlainText
from app.services import possession as pos_svc
from app.services import postsales as cases
from app.services import receipts as files
from app.services.audit import log_audit
from app.services.notifications import notify

router = APIRouter(tags=["after-sales"])
Viewer = Annotated[User, Depends(require_role(*POSTSALES_ROLES))]
SERVICE = (
    Role.admin,
    Role.crm_manager,
    Role.after_sales,
    Role.service,
    Role.site,
    Role.project_manager,
)
RAISERS = (*SERVICE, Role.postsales_exec)
CONFIG = (Role.admin, Role.crm_manager, Role.legal)
IST = timezone(timedelta(hours=5, minutes=30))
CATEGORIES = (
    "civil",
    "structural",
    "waterproofing",
    "electrical",
    "plumbing",
    "finishing",
    "fittings",
    "equipment",
    "other",
)
Txt = Annotated[PlainText, StringConstraints(min_length=2, max_length=2000)]


def now() -> datetime:
    return datetime.now(UTC)


def today() -> date:
    return now().astimezone(IST).date()


def add_months(d: date, months: int) -> date:
    y, m = divmod(d.month - 1 + months, 12)
    y, m = d.year + y, m + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def _who(ok: bool, msg: str) -> None:
    if not ok:
        raise HTTPException(status.HTTP_403_FORBIDDEN, msg)


# ------------------------------------------------------------------ warranty catalogue and FM handover (per project)
class WarrantyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: int | None = None
    name: Annotated[PlainText, StringConstraints(min_length=2, max_length=150)]
    category: Literal[
        "civil",
        "structural",
        "waterproofing",
        "electrical",
        "plumbing",
        "finishing",
        "fittings",
        "equipment",
        "other",
    ]
    provider: Annotated[PlainText, StringConstraints(max_length=150)] | None = None
    period_months: Annotated[int, Field(ge=1, le=240)]
    starts_from: Literal["possession", "completion", "purchase"] = "possession"
    basis: Annotated[PlainText, StringConstraints(max_length=300)] | None = None
    active: bool = True


class FacilityIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    maintenance_start: date | None = None
    maintenance_contacts: Annotated[PlainText, StringConstraints(max_length=1000)] | None = None
    facilities: Annotated[PlainText, StringConstraints(max_length=3000)] | None = None
    manuals: Annotated[PlainText, StringConstraints(max_length=2000)] | None = None
    utilities: Annotated[PlainText, StringConstraints(max_length=2000)] | None = None
    records_handed_to: Annotated[PlainText, StringConstraints(max_length=200)] | None = None
    records_handed_on: date | None = None
    customer_guidance: Annotated[PlainText, StringConstraints(max_length=3000)] | None = None


async def _project(db: DbSession, pid: int) -> Project:
    p = await db.get(Project, pid)
    if p is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    return p


async def warranties(db: DbSession, pid: int) -> list[WarrantyItem]:
    return list(
        await db.scalars(
            select(WarrantyItem).where(WarrantyItem.project_id == pid).order_by(WarrantyItem.id)
        )
    )


def w_out(w: WarrantyItem) -> dict:
    return {
        "id": w.id,
        "name": w.name,
        "category": w.category,
        "provider": w.provider,
        "period_months": w.period_months,
        "starts_from": w.starts_from,
        "basis": w.basis,
        "active": w.active,
    }


@router.get("/projects/{pid}/after-sales")
async def project_after_sales(pid: int, user: Viewer, db: DbSession) -> dict:
    await _project(db, pid)
    fm = await db.get(FacilityHandover, pid)
    common = list(
        await db.scalars(
            select(Defect)
            .where(Defect.project_id == pid, Defect.case_id.is_(None), Defect.status != "closed")
            .order_by(Defect.id)
        )
    )
    return {
        "warranties": [w_out(w) for w in await warranties(db, pid)],
        "facility": fm.data if fm else {},
        "can_edit": user.role in CONFIG,
        "pending_common_area_defects": [
            {
                "id": d.id,
                "number": f"DEF-{d.id:05d}",
                "description": d.description,
                "location": d.location,
                "status": d.status,
            }
            for d in common
        ],
    }


@router.put("/projects/{pid}/warranties")
async def put_warranties(
    pid: int,
    body: Annotated[list[WarrantyIn], Field(max_length=60)],
    request: Request,
    user: Viewer,
    db: DbSession,
) -> dict:
    """The project's warranty and defect-liability terms. Items used by defects are deactivated, never deleted."""
    _who(user.role in CONFIG, "Admins, CRM managers or legal set the warranty terms")
    await _project(db, pid)
    existing = {w.id: w for w in await warranties(db, pid)}
    keep = set()
    for item in body:
        if item.id is not None:
            w = existing.get(item.id)
            if w is None:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_CONTENT,
                    "That warranty item isn't on this project",
                )
            for k, v in item.model_dump(exclude={"id"}).items():
                setattr(w, k, v)
            keep.add(w.id)
        else:
            db.add(WarrantyItem(project_id=pid, **item.model_dump(exclude={"id"})))
    for wid, w in existing.items():
        if wid not in keep:
            used = await db.scalar(
                select(func.count()).select_from(Defect).where(Defect.warranty_item_id == wid)
            )
            if used:
                w.active = False
            else:
                await db.delete(w)
    log_audit(
        db,
        action="aftersales.warranties",
        entity_type="project",
        entity_id=pid,
        actor=user,
        details={"items": [i.name for i in body]},
        request=request,
    )
    await db.commit()
    return await project_after_sales(pid, user, db)


@router.put("/projects/{pid}/facility-handover")
async def put_facility(
    pid: int, body: FacilityIn, request: Request, user: Viewer, db: DbSession
) -> dict:
    _who(user.role in CONFIG, "Admins, CRM managers or legal record the facility handover")
    await _project(db, pid)
    fm = await db.get(FacilityHandover, pid)
    data = {**body.model_dump(mode="json"), "by": user.full_name, "at": now().isoformat()}
    if fm is None:
        db.add(FacilityHandover(project_id=pid, data=data, updated_by_id=user.id))
    else:
        fm.data, fm.updated_by_id = data, user.id
    log_audit(
        db,
        action="aftersales.facility_handover",
        entity_type="project",
        entity_id=pid,
        actor=user,
        details={"records_handed_to": body.records_handed_to},
        request=request,
    )
    await db.commit()
    return await project_after_sales(pid, user, db)


# ------------------------------------------------------------------ warranty dates for a customer
async def start_dates(
    db: DbSession, project: Project, case: PostSalesCase | None
) -> dict[str, date | None]:
    trigger, _ = await pos_svc.trigger_reached(db, project)
    m = (
        await db.scalar(
            select(ProjectMilestone).where(
                ProjectMilestone.project_id == project.id,
                func.lower(ProjectMilestone.name) == (trigger or "").lower(),
            )
        )
        if trigger
        else None
    )
    completion = m.completed_on if m and m.status == MilestoneStatus.verified else None
    possession = None
    if case is not None:
        f = await db.scalar(select(PossessionFile).where(PossessionFile.case_id == case.id))
        possession = f.actual_possession_on if f else None
    return {
        "possession": possession or (None if case else completion),
        "completion": completion,
        "purchase": case.booking.booking_date if case else None,
    }


def coverage(w: WarrantyItem, starts: dict) -> dict:
    s = starts.get(w.starts_from)
    end = add_months(s, w.period_months) - timedelta(days=1) if s else None
    return {"start": s, "end": end, "in_warranty": None if end is None else today() <= end}


# ------------------------------------------------------------------ defects
class RaiseIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    case_id: int | None = None  # none = common area (give project_id)
    project_id: int | None = None
    complaint_date: date | None = None
    channel: Literal["phone", "email", "whatsapp", "walk_in", "letter", "portal", "other"] = "phone"
    category: Literal[
        "civil",
        "structural",
        "waterproofing",
        "electrical",
        "plumbing",
        "finishing",
        "fittings",
        "equipment",
        "other",
    ]
    description: Txt
    location: Annotated[PlainText, StringConstraints(max_length=120)] | None = None
    item: Annotated[PlainText, StringConstraints(max_length=150)] | None = None
    warranty_item_id: int | None = None
    owner_id: int | None = None


class StepIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    step: Literal[
        "acknowledge",
        "schedule",
        "diagnose",
        "responsibility",
        "customer_approval",
        "start",
        "complete",
        "quality",
        "customer",
        "close",
    ]
    data: dict[str, Any] = {}


ORDER = {
    "acknowledge": ("raised",),
    "schedule": ("acknowledged",),
    "diagnose": ("inspection_scheduled",),
    "responsibility": ("diagnosed",),
    "customer_approval": ("awaiting_customer_approval",),
    "start": ("responsibility_assigned", "reopened"),
    "complete": ("in_rectification",),
    "quality": ("quality_check",),
    "customer": ("customer_update",),
}
NEXT = {
    "acknowledge": "acknowledged",
    "schedule": "inspection_scheduled",
    "diagnose": "diagnosed",
    "start": "in_rectification",
    "complete": "quality_check",
    "quality": "customer_update",
}


def code(d: Defect) -> str:
    return f"DEF-{d.id:05d}"


def _text(data: dict, key: str, label: str, min_len: int = 3, max_len: int = 2000) -> str:
    v = str(data.get(key) or "").strip()
    if len(v) < min_len:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Give the {label}")
    if len(v) > max_len or "<" in v or ">" in v:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Check the {label}")
    return v


def _date(data: dict, key: str, label: str) -> date:
    try:
        return date.fromisoformat(str(data.get(key)))
    except ValueError:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Give the {label}") from None


async def d_out(db: DbSession, d: Defect, user: User) -> dict:
    ids = {x for x in (d.owner_id, d.raised_by_id) if x}
    users = (
        {u.id: u.full_name for u in await db.scalars(select(User).where(User.id.in_(ids)))}
        if ids
        else {}
    )
    w = await db.get(WarrantyItem, d.warranty_item_id) if d.warranty_item_id else None
    fs = list(
        await db.scalars(
            select(DefectFile).where(DefectFile.defect_id == d.id).order_by(DefectFile.id)
        )
    )
    case = await db.get(PostSalesCase, d.case_id) if d.case_id else None
    st, steps = d.status, d.steps or {}
    r = user.role
    completed_by = (steps.get("completed") or {}).get("by")
    nxt = {
        "raised": ["acknowledge"],
        "acknowledged": ["schedule"],
        "inspection_scheduled": ["diagnose"],
        "diagnosed": ["responsibility"],
        "awaiting_customer_approval": ["customer_approval"],
        "responsibility_assigned": ["start"],
        "reopened": ["start"],
        "in_rectification": ["complete"],
        "quality_check": ["quality"],
        "customer_update": ["customer"],
    }.get(st, [])
    allowed = [
        s
        for s in nxt
        if (r in SERVICE if s not in ("customer", "customer_approval") else r in RAISERS)
        and not (s == "quality" and completed_by == user.id)
    ]
    return {
        "id": d.id,
        "number": code(d),
        "project_id": d.project_id,
        "case_id": d.case_id,
        "customer": case.booking.lead.name if case else None,
        "unit": case.booking.unit.unit_no if case else "Common area",
        "status": st,
        "complaint_date": d.complaint_date,
        "channel": d.channel,
        "category": d.category,
        "description": d.description,
        "location": d.location,
        "item": d.item,
        "warranty": {"name": w.name, "provider": w.provider, "basis": w.basis} if w else None,
        "warranty_start": d.warranty_start,
        "warranty_end": d.warranty_end,
        "in_warranty": None if d.warranty_end is None else d.complaint_date <= d.warranty_end,
        "owner": users.get(d.owner_id),
        "raised_by": users.get(d.raised_by_id),
        "steps": steps,
        "target_date": d.target_date,
        "overdue": d.target_date is not None
        and d.status not in ("closed", "customer_update")
        and d.target_date < today(),
        "reopened_count": d.reopened_count,
        "closure_reason": d.closure_reason,
        "closed_at": d.closed_at,
        "created_at": d.created_at,
        "files": [
            {
                "id": x.id,
                "kind": x.kind,
                "file_name": x.file_name,
                "url": f"/api/defects/files/{x.id}",
            }
            for x in fs
        ],
        "next": allowed,
        "can_close": st != "closed" and r in (Role.admin, Role.crm_manager),
    }


async def _defect(db: DbSession, did: int) -> Defect:
    d = await db.get(Defect, did)
    if d is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Defect not found")
    return d


@router.get("/defects")
async def list_defects(
    user: Viewer,
    db: DbSession,
    project_id: int | None = None,
    case_id: int | None = None,
    open_only: bool = False,
) -> list[dict]:
    q = select(Defect)
    if project_id:
        q = q.where(Defect.project_id == project_id)
    if case_id:
        q = q.where(Defect.case_id == case_id)
    if open_only:
        q = q.where(Defect.status != "closed")
    return [
        await d_out(db, d, user) for d in await db.scalars(q.order_by(Defect.id.desc()).limit(300))
    ]


@router.post("/defects", status_code=status.HTTP_201_CREATED)
async def raise_defect(body: RaiseIn, request: Request, user: Viewer, db: DbSession) -> dict:
    _who(user.role in RAISERS, "Post-sales or the service team records complaints")
    case = None
    if body.case_id is not None:
        case = await db.get(PostSalesCase, body.case_id)
        if case is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Case not found")
        project = await db.get(Project, case.booking.project_id)
    elif body.project_id is not None:
        project = await _project(db, body.project_id)
    else:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Choose the customer's case, or the project for a common-area defect",
        )
    cd = body.complaint_date or today()
    if cd > today():
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "The complaint date can't be in the future"
        )
    w_start = w_end = None
    if body.warranty_item_id is not None:
        w = await db.get(WarrantyItem, body.warranty_item_id)
        if w is None or w.project_id != project.id or not w.active:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, "Choose one of this project's warranty items"
            )
        cov = coverage(w, await start_dates(db, project, case))
        w_start, w_end = cov["start"], cov["end"]
    owner = body.owner_id
    if owner is not None:
        u = await db.get(User, owner)
        if u is None or not u.is_active or u.role not in SERVICE:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, "Choose an active after-sales or site person"
            )
    d = Defect(
        project_id=project.id,
        case_id=case.id if case else None,
        complaint_date=cd,
        channel=body.channel,
        category=body.category,
        description=body.description,
        location=body.location,
        item=body.item,
        warranty_item_id=body.warranty_item_id,
        warranty_start=w_start,
        warranty_end=w_end,
        owner_id=owner,
        raised_by_id=user.id,
        steps={},
    )
    db.add(d)
    await db.flush()
    if case:
        cases.event(db, case, "defect_raised", user, {"defect": code(d), "category": body.category})
    log_audit(
        db,
        action="aftersales.defect_raised",
        entity_type="defect",
        entity_id=d.id,
        actor=user,
        details={"category": body.category, "case": body.case_id},
        request=request,
    )
    for uid in (
        [owner]
        if owner
        else list(
            await db.scalars(
                select(User.id).where(User.is_active.is_(True), User.role == Role.after_sales)
            )
        )
    ):
        if uid != user.id:
            notify(
                db,
                user_id=uid,
                type="defect_raised",
                title=f"Defect complaint: {case.booking.lead.name if case else project.name + ' (common area)'}",
                body=f"{code(d)} {body.category}: {body.description[:120]}",
                link=f"/post-sales/{case.id}?tab=aftersales"
                if case
                else f"/projects/{project.id}#after-sales",
            )
    await db.commit()
    return await d_out(db, d, user)


@router.post("/defects/{did}/step")
async def step(did: int, body: StepIn, request: Request, user: Viewer, db: DbSession) -> dict:
    """The defect workflow, one step at a time, each with its own rule."""
    d = await _defect(db, did)
    s, data, steps = body.step, body.data, dict(d.steps or {})
    stamp = {"by": user.id, "by_name": user.full_name, "at": now().isoformat()}
    if s == "close":
        _who(
            user.role in (Role.admin, Role.crm_manager),
            "A CRM manager or admin closes a defect without the full workflow",
        )
        if d.status == "closed":
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Already closed")
        d.status, d.closure_reason, d.closed_at = (
            "closed",
            _text(data, "reason", "closure reason (e.g. duplicate, not a defect)"),
            now(),
        )
    else:
        _who(
            user.role in (RAISERS if s in ("customer", "customer_approval") else SERVICE),
            "Your role can't take this step",
        )
        if d.status not in ORDER[s]:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                f"Not possible while the defect is {d.status.replace('_', ' ')}",
            )
        if s == "acknowledge":
            steps["acknowledged"] = {**stamp, "note": str(data.get("note") or "").strip() or None}
            d.owner_id = d.owner_id or user.id
        elif s == "schedule":
            visit = _date(data, "visit_on", "visit date")
            if visit < today():
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_CONTENT, "The visit can't be in the past"
                )
            steps["inspection"] = {
                **stamp,
                "visit_on": visit.isoformat(),
                "availability": _text(data, "availability", "customer's availability", 2, 300),
            }
        elif s == "diagnose":
            visited = _date(data, "visited_on", "actual visit date")
            if visited > today():
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_CONTENT, "The visit date can't be in the future"
                )
            steps["diagnosis"] = {
                **stamp,
                "visited_on": visited.isoformat(),
                "text": _text(data, "diagnosis", "diagnosis"),
            }
        elif s == "responsibility":
            party = str(data.get("party") or "")
            if party not in ("developer", "contractor", "manufacturer", "customer", "society"):
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_CONTENT, "Choose who is responsible"
                )
            covered = bool(data.get("covered"))
            entry = {**stamp, "party": party, "covered": covered}
            if not covered:
                entry["reason"] = _text(data, "reason", "reason it isn't covered")
                try:
                    entry["estimate"] = int(data.get("estimate"))
                except (TypeError, ValueError):
                    raise HTTPException(
                        status.HTTP_422_UNPROCESSABLE_CONTENT,
                        "Give the estimate for chargeable work (0 if none)",
                    ) from None
                if entry["estimate"] < 0:
                    raise HTTPException(
                        status.HTTP_422_UNPROCESSABLE_CONTENT, "The estimate can't be negative"
                    )
                if not await db.scalar(
                    select(DefectFile.id).where(
                        DefectFile.defect_id == d.id,
                        DefectFile.kind.in_(["diagnosis", "not_covered"]),
                    )
                ):
                    raise HTTPException(
                        status.HTTP_422_UNPROCESSABLE_CONTENT,
                        "Attach the supporting evidence (diagnosis photo or report) before marking it not covered",
                    )
            steps["responsibility"] = entry
            d.status = "responsibility_assigned" if covered else "awaiting_customer_approval"
        elif s == "customer_approval":
            approved = bool(data.get("approved"))
            steps["customer_approval"] = {
                **stamp,
                "approved": approved,
                "on": _date(data, "on", "date of the customer's decision").isoformat(),
            }
            if approved:
                d.status = "responsibility_assigned"
            else:
                d.status, d.closure_reason, d.closed_at = (
                    "closed",
                    "Not covered; the customer declined the chargeable work",
                    now(),
                )
        elif s == "start":
            if steps.get("responsibility", {}).get("covered") is False and not steps.get(
                "customer_approval", {}
            ).get("approved"):
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_CONTENT,
                    "Chargeable work needs the customer's approval first",
                )
            target = _date(data, "target", "rectification target date")
            if target < today():
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_CONTENT, "The target can't be in the past"
                )
            action = str(data.get("action") or "")
            if action not in ("repair", "replace"):
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_CONTENT, "Choose repair or replace"
                )
            steps["rectification"] = {
                **stamp,
                "action": action,
                "contractor": _text(data, "contractor", "contractor or team", 2, 150),
                "target": target.isoformat(),
            }
            d.target_date = target
        elif s == "complete":
            steps["completed"] = {
                **stamp,
                "work": _text(data, "work", "work done"),
                "materials": str(data.get("materials") or "").strip() or None,
            }
        elif s == "quality":
            if (steps.get("completed") or {}).get("by") == user.id:
                raise HTTPException(
                    status.HTTP_403_FORBIDDEN,
                    "Someone other than the person who did the work checks the quality",
                )
            steps["quality"] = {**stamp, "note": str(data.get("note") or "").strip() or None}
        elif s == "customer":
            response = str(data.get("response") or "")
            if response not in ("accepted", "disputed"):
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_CONTENT,
                    "Record whether the customer accepted or disputed the repair",
                )
            note = str(data.get("note") or "").strip() or None
            if response == "disputed" and not note:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_CONTENT, "Record what the customer disputes"
                )
            steps.setdefault("customer_history", []).append(
                {**stamp, "response": response, "note": note}
            )
            if response == "accepted":
                d.status, d.closed_at, d.closure_reason = (
                    "closed",
                    now(),
                    "Rectified; customer confirmed",
                )
            else:
                d.status, d.reopened_count = "reopened", d.reopened_count + 1
                steps.pop("completed", None)
                steps.pop("quality", None)
        if s in NEXT:
            d.status = NEXT[s]
    d.steps = steps
    log_audit(
        db,
        action=f"aftersales.defect_{s}",
        entity_type="defect",
        entity_id=d.id,
        actor=user,
        details={"status": d.status},
        request=request,
    )
    if d.case_id:
        case = await db.get(PostSalesCase, d.case_id)
        cases.event(db, case, f"defect_{d.status}", user, {"defect": code(d)})
    from app.services import comms

    if d.status == "customer_update" and d.case_id:
        await comms.emit(
            db,
            "defect_rectified",
            await db.get(PostSalesCase, d.case_id),
            {"defect_no": code(d), "description": d.description[:80]},
            f"{d.id}:{d.reopened_count}",
        )
    await db.commit()
    return await d_out(db, d, user)


@router.post("/defects/{did}/files")
async def defect_file(
    did: int,
    request: Request,
    user: Viewer,
    db: DbSession,
    file: Annotated[UploadFile, File()],
    kind: Annotated[
        Literal["complaint", "diagnosis", "completion", "not_covered"], Form()
    ] = "complaint",
) -> dict:
    _who(user.role in RAISERS, "Post-sales or the service team adds evidence")
    d = await _defect(db, did)
    try:
        path, name, mime = await files.save_receipt(
            file, folder="defects", max_mb=15, what="Photos"
        )
    except files.ReceiptError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
    db.add(
        DefectFile(
            defect_id=d.id,
            kind=kind,
            file_path=path,
            file_name=name,
            file_type=mime,
            uploaded_by_id=user.id,
        )
    )
    await db.commit()
    return await d_out(db, d, user)


@router.get("/defects/files/{fid}")
async def defect_file_get(fid: int, _: Viewer, db: DbSession) -> FileResponse:
    f = await db.get(DefectFile, fid)
    if f is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found")
    path = files.receipt_file(f.file_path, "defects")
    if not path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "The file is missing")
    return FileResponse(
        path,
        media_type=f.file_type,
        headers={"Content-Disposition": f'inline; filename="{f.file_name}"'},
    )


@router.get("/post-sales/cases/{case_id}/after-sales")
async def case_after_sales(case_id: int, user: Viewer, db: DbSession) -> dict:
    """The customer's after-sales view: transfer status, warranty coverage with real dates, guidance, defects."""
    case = await db.get(PostSalesCase, case_id)
    if case is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Case not found")
    project = await db.get(Project, case.booking.project_id)
    f = await db.scalar(select(PossessionFile).where(PossessionFile.case_id == case.id))
    starts = await start_dates(db, project, case)
    fm = await db.get(FacilityHandover, project.id)
    return {
        "project_id": project.id,
        "after_sales_since": f.after_sales_since if f else None,
        "possession_on": f.actual_possession_on if f else None,
        "warranties": [
            {**w_out(w), **coverage(w, starts)}
            for w in await warranties(db, project.id)
            if w.active
        ],
        "guidance": (fm.data or {}).get("customer_guidance") if fm else None,
        "maintenance_contacts": (fm.data or {}).get("maintenance_contacts") if fm else None,
        "defects": await list_defects(user, db, case_id=case.id),
        "can_raise": user.role in RAISERS,
        "categories": list(CATEGORIES),
        "owners": [
            {"id": u.id, "full_name": u.full_name}
            for u in await db.scalars(
                select(User)
                .where(User.is_active.is_(True), User.role.in_(list(SERVICE)))
                .order_by(User.full_name)
            )
        ],
    }


async def run_defect_reminders(db, today_: date, send) -> dict:
    n = 0
    for d in await db.scalars(
        select(Defect).where(
            Defect.status.in_(["in_rectification", "reopened"]),
            Defect.target_date < today_,
            (Defect.reminded_on.is_(None)) | (Defect.reminded_on < today_),
        )
    ):
        who = (
            [d.owner_id]
            if d.owner_id
            else list(
                await db.scalars(
                    select(User.id).where(User.is_active.is_(True), User.role == Role.crm_manager)
                )
            )
        )
        n += await send(
            who,
            type="defect_overdue",
            title=f"Overdue defect {code(d)}",
            body=f"{d.description[:120]} (target {d.target_date.isoformat()})",
            link=f"/post-sales/{d.case_id}?tab=aftersales"
            if d.case_id
            else f"/projects/{d.project_id}#after-sales",
        )
        d.reminded_on = today_
    return {"defects_overdue": n}
