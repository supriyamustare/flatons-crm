from datetime import date
from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse
from sqlalchemy import func, select

from app.core.deps import DbSession, require_role
from app.models.lead import Lead
from app.models.marketing import Campaign, Expense, ExpenseCategory
from app.models.project import Project
from app.models.user import Role, User
from app.schemas.marketing import (
    CampaignCreate,
    CampaignOut,
    CampaignUpdate,
    ExpenseOut,
    ExpensePage,
    ExpenseQuery,
    ExpenseUpdate,
)
from app.services import receipts
from app.services.audit import log_audit

router = APIRouter(tags=["marketing"])
Marketer = Annotated[User, Depends(require_role(Role.admin, Role.manager))]
# Executives may pick a campaign when entering a lead, but never see spend.
Sales = Annotated[User, Depends(require_role(Role.admin, Role.manager, Role.executive))]


def _422(msg: str) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, msg)


async def _campaign_or_404(db: DbSession, campaign_id: int) -> Campaign:
    c = await db.get(Campaign, campaign_id)
    if c is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Campaign not found")
    return c


async def _check_project(db: DbSession, project_id: int | None) -> None:
    if project_id is not None and await db.get(Project, project_id) is None:
        raise _422("That project doesn't exist")


def _expense_out(e: Expense) -> ExpenseOut:
    out = ExpenseOut.model_validate(e)
    out.has_receipt = bool(e.receipt_path)
    return out


# ---- Campaigns ---------------------------------------------------------------


@router.get("/campaigns", response_model=list[CampaignOut])
async def list_campaigns(_: Sales, db: DbSession) -> list[Campaign]:
    return list(
        await db.scalars(select(Campaign).order_by(Campaign.start_date.desc(), Campaign.name))
    )


@router.post("/campaigns", response_model=CampaignOut, status_code=status.HTTP_201_CREATED)
async def create_campaign(
    body: CampaignCreate, request: Request, user: Marketer, db: DbSession
) -> Campaign:
    if await db.scalar(select(Campaign.id).where(Campaign.name.ilike(body.name))):
        raise HTTPException(status.HTTP_409_CONFLICT, "A campaign with this name already exists")
    await _check_project(db, body.project_id)
    c = Campaign(**body.model_dump(), created_by_id=user.id)
    db.add(c)
    await db.flush()
    log_audit(
        db,
        action="campaign.create",
        entity_type="campaign",
        entity_id=c.id,
        actor=user,
        details={"name": c.name, "channel": c.channel.value},
        request=request,
    )
    await db.commit()
    await db.refresh(c)
    return c


@router.patch("/campaigns/{campaign_id}", response_model=CampaignOut)
async def update_campaign(
    campaign_id: int, body: CampaignUpdate, request: Request, user: Marketer, db: DbSession
) -> Campaign:
    c = await _campaign_or_404(db, campaign_id)
    changes = body.model_dump(exclude_unset=True)
    if "name" in changes and await db.scalar(
        select(Campaign.id).where(Campaign.name.ilike(changes["name"]), Campaign.id != c.id)
    ):
        raise HTTPException(status.HTTP_409_CONFLICT, "A campaign with this name already exists")
    if "project_id" in changes:
        await _check_project(db, changes["project_id"])
    start = changes.get("start_date", c.start_date)
    end = changes.get("end_date", c.end_date)
    if start is None:
        raise _422("A campaign needs a start date")
    if end is not None and end < start:
        raise _422("The end date can't be before the start date")
    for k, v in changes.items():
        setattr(c, k, v)
    log_audit(
        db,
        action="campaign.update",
        entity_type="campaign",
        entity_id=c.id,
        actor=user,
        details={k: str(v) for k, v in changes.items()},
        request=request,
    )
    await db.commit()
    await db.refresh(c)
    return c


@router.delete("/campaigns/{campaign_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_campaign(
    campaign_id: int, request: Request, user: Marketer, db: DbSession
) -> None:
    c = await _campaign_or_404(db, campaign_id)
    if await db.scalar(
        select(func.count()).select_from(Expense).where(Expense.campaign_id == c.id)
    ):
        raise HTTPException(
            status.HTTP_409_CONFLICT, "This campaign has expenses; delete those first"
        )
    if await db.scalar(select(func.count()).select_from(Lead).where(Lead.campaign_id == c.id)):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Leads are attributed to this campaign, so it can't be deleted",
        )
    log_audit(
        db,
        action="campaign.delete",
        entity_type="campaign",
        entity_id=c.id,
        actor=user,
        details={"name": c.name},
        request=request,
    )
    await db.delete(c)
    await db.commit()


# ---- Expenses ----------------------------------------------------------------


@router.get("/expenses", response_model=ExpensePage)
async def list_expenses(
    q: Annotated[ExpenseQuery, Query()], _: Marketer, db: DbSession
) -> ExpensePage:
    stmt = select(Expense).join(Campaign, Campaign.id == Expense.campaign_id)
    if q.campaign_id:
        stmt = stmt.where(Expense.campaign_id == q.campaign_id)
    if q.channel:
        stmt = stmt.where(Campaign.channel == q.channel)
    if q.project_id:
        stmt = stmt.where(Campaign.project_id == q.project_id)
    if q.date_from:
        stmt = stmt.where(Expense.spent_on >= q.date_from)
    if q.date_to:
        stmt = stmt.where(Expense.spent_on <= q.date_to)
    sub = stmt.subquery()
    total, amount = (
        await db.execute(select(func.count(), func.coalesce(func.sum(sub.c.amount), 0)))
    ).one()
    by_channel = dict(
        (
            await db.execute(
                select(Campaign.channel, func.sum(sub.c.amount))
                .join(Campaign, Campaign.id == sub.c.campaign_id)
                .group_by(Campaign.channel)
            )
        ).all()
    )
    items = await db.scalars(
        stmt.order_by(Expense.spent_on.desc(), Expense.id.desc())
        .offset((q.page - 1) * q.page_size)
        .limit(q.page_size)
    )
    return ExpensePage(
        items=[_expense_out(e) for e in items],
        total=total,
        page=q.page,
        page_size=q.page_size,
        total_amount=int(amount),
        by_channel={k: int(v) for k, v in by_channel.items()},
    )


@router.post("/expenses", response_model=ExpenseOut, status_code=status.HTTP_201_CREATED)
async def create_expense(
    request: Request,
    user: Marketer,
    db: DbSession,
    campaign_id: Annotated[int, Form()],
    spent_on: Annotated[date, Form()],
    amount: Annotated[int, Form(gt=0, le=1_000_000_000)],
    category: Annotated[ExpenseCategory, Form()],
    vendor: Annotated[str | None, Form(max_length=150)] = None,
    notes: Annotated[str | None, Form(max_length=500)] = None,
    receipt: Annotated[UploadFile | None, File()] = None,
) -> ExpenseOut:
    """Multipart form: the expense fields plus an optional receipt (PDF, JPG or PNG, max 10 MB)."""
    await _campaign_or_404(db, campaign_id)
    for text in (vendor, notes):
        if text and ("<" in text or ">" in text):
            raise _422("Vendor and notes can't contain < or >")
    e = Expense(
        campaign_id=campaign_id,
        spent_on=spent_on,
        amount=amount,
        category=category,
        vendor=(vendor or "").strip() or None,
        notes=(notes or "").strip() or None,
        entered_by_id=user.id,
    )
    if receipt is not None and receipt.filename:
        try:
            e.receipt_path, e.receipt_name, e.receipt_type = await receipts.save_receipt(receipt)
        except receipts.ReceiptError as exc:
            raise _422(str(exc)) from None
    db.add(e)
    await db.flush()
    log_audit(
        db,
        action="expense.create",
        entity_type="expense",
        entity_id=e.id,
        actor=user,
        details={"campaign_id": campaign_id, "amount": amount, "receipt": bool(e.receipt_path)},
        request=request,
    )
    await db.commit()
    await db.refresh(e)
    return _expense_out(e)


async def _expense_or_404(db: DbSession, expense_id: int) -> Expense:
    e = await db.get(Expense, expense_id)
    if e is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Expense not found")
    return e


@router.patch("/expenses/{expense_id}", response_model=ExpenseOut)
async def update_expense(
    expense_id: int, body: ExpenseUpdate, request: Request, user: Marketer, db: DbSession
) -> ExpenseOut:
    e = await _expense_or_404(db, expense_id)
    changes = body.model_dump(exclude_unset=True)
    if changes.get("campaign_id") is not None:
        await _campaign_or_404(db, changes["campaign_id"])
    for required in ("campaign_id", "spent_on", "amount", "category"):
        if required in changes and changes[required] is None:
            raise _422(f"{required.replace('_', ' ').capitalize()} can't be empty")
    before = {k: str(getattr(e, k)) for k in changes}
    for k, v in changes.items():
        setattr(e, k, v)
    log_audit(
        db,
        action="expense.update",
        entity_type="expense",
        entity_id=e.id,
        actor=user,
        details={"from": before, "to": {k: str(v) for k, v in changes.items()}},
        request=request,
    )
    await db.commit()
    await db.refresh(e)
    return _expense_out(e)


@router.post("/expenses/{expense_id}/receipt", response_model=ExpenseOut)
async def replace_receipt(
    expense_id: int,
    request: Request,
    user: Marketer,
    db: DbSession,
    receipt: Annotated[UploadFile, File()],
) -> ExpenseOut:
    e = await _expense_or_404(db, expense_id)
    try:
        stored, name, mime = await receipts.save_receipt(receipt)
    except receipts.ReceiptError as exc:
        raise _422(str(exc)) from None
    old = e.receipt_path
    e.receipt_path, e.receipt_name, e.receipt_type = stored, name, mime
    log_audit(
        db,
        action="expense.receipt",
        entity_type="expense",
        entity_id=e.id,
        actor=user,
        request=request,
    )
    await db.commit()
    receipts.delete_receipt(old)
    await db.refresh(e)
    return _expense_out(e)


@router.get("/expenses/{expense_id}/receipt")
async def download_receipt(expense_id: int, _: Marketer, db: DbSession) -> FileResponse:
    e = await _expense_or_404(db, expense_id)
    if not e.receipt_path:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No receipt for this expense")
    path = receipts.receipt_file(e.receipt_path)
    if not path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "The receipt file is missing")
    return FileResponse(
        path,
        media_type=e.receipt_type or "application/octet-stream",
        filename=e.receipt_name or path.name,
        headers={"Cache-Control": "private, no-store"},
    )


@router.delete("/expenses/{expense_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_expense(expense_id: int, request: Request, user: Marketer, db: DbSession) -> None:
    e = await _expense_or_404(db, expense_id)
    stored = e.receipt_path
    log_audit(
        db,
        action="expense.delete",
        entity_type="expense",
        entity_id=e.id,
        actor=user,
        details={"campaign_id": e.campaign_id, "amount": e.amount, "spent_on": str(e.spent_on)},
        request=request,
    )
    await db.delete(e)
    await db.commit()
    receipts.delete_receipt(stored)
