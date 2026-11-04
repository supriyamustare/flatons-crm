from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, StringConstraints, field_validator

from app.core.crypto import decrypt, encrypt
from app.core.deps import DbSession, require_role
from app.models.project import Project
from app.models.project_legal import ProjectBank, ProjectLegal
from app.models.user import Role, User
from app.schemas.common import LongText, PlainText
from app.schemas.ids import CIN, GSTIN, IFSC, RERA, AccountNumber
from app.services import doc_readiness
from app.services.audit import log_audit

router = APIRouter(tags=["project legal and bank details"])
Admin = Annotated[User, Depends(require_role(Role.admin))]
Manager = Annotated[User, Depends(require_role(Role.admin, Role.manager))]
DocsOrManager = Annotated[User, Depends(require_role(Role.admin, Role.manager, Role.docs))]


class LegalIn(BaseModel):
    """Everything is optional while being filled in; readiness says what's still missing."""

    model_config = ConfigDict(extra="forbid")
    developer_legal_name: Annotated[PlainText, StringConstraints(max_length=200)] | None = None
    rera_number: RERA | None = None
    registered_address: LongText | None = None
    signatory_name: Annotated[PlainText, StringConstraints(max_length=150)] | None = None
    signatory_designation: Annotated[PlainText, StringConstraints(max_length=100)] | None = None
    gstin: GSTIN | None = None
    cin: CIN | None = None

    @field_validator(
        "developer_legal_name",
        "registered_address",
        "signatory_name",
        "signatory_designation",
        mode="before",
    )
    @classmethod
    def _blank(cls, v):
        return None if isinstance(v, str) and not v.strip() else v


class LegalOut(LegalIn):
    model_config = ConfigDict(from_attributes=True, extra="ignore")
    updated_at: datetime | None = None


class BankIn(BaseModel):
    """account_number: leave out to keep the saved one."""

    model_config = ConfigDict(extra="forbid")
    bank_name: Annotated[PlainText, StringConstraints(max_length=150)] | None = None
    account_holder_name: Annotated[PlainText, StringConstraints(max_length=200)] | None = None
    account_number: AccountNumber | None = None
    ifsc: IFSC | None = None
    branch: Annotated[PlainText, StringConstraints(max_length=150)] | None = None


class BankOut(BaseModel):
    bank_name: str | None
    account_holder_name: str | None
    account_number_masked: str | None  # ••••1234
    account_number: str | None = None  # only when revealed
    ifsc: str | None
    branch: str | None
    updated_at: datetime | None


async def _project(db: DbSession, project_id: int) -> Project:
    p = await db.get(Project, project_id)
    if p is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    return p


@router.get("/projects/{project_id}/legal", response_model=LegalOut)
async def get_legal(project_id: int, _: Manager, db: DbSession) -> LegalOut:
    await _project(db, project_id)
    legal = await db.get(ProjectLegal, project_id)
    return LegalOut.model_validate(legal) if legal else LegalOut()


@router.put("/projects/{project_id}/legal", response_model=LegalOut)
async def put_legal(
    project_id: int, body: LegalIn, request: Request, admin: Admin, db: DbSession
) -> LegalOut:
    await _project(db, project_id)
    legal = await db.get(ProjectLegal, project_id) or ProjectLegal(project_id=project_id)
    before = {k: getattr(legal, k, None) for k in LegalIn.model_fields}
    for k, v in body.model_dump().items():
        setattr(legal, k, v)
    legal.updated_by_id = admin.id
    db.add(legal)
    changed = {
        k: {"from": before[k], "to": v} for k, v in body.model_dump().items() if before[k] != v
    }
    if changed:
        log_audit(
            db,
            action="project.legal",
            entity_type="project",
            entity_id=project_id,
            actor=admin,
            details=changed,
            request=request,
        )
    await db.commit()
    await db.refresh(legal)
    return LegalOut.model_validate(legal)


def _bank_out(bank: ProjectBank | None, reveal: bool = False) -> BankOut:
    if bank is None:
        return BankOut(
            bank_name=None,
            account_holder_name=None,
            account_number_masked=None,
            ifsc=None,
            branch=None,
            updated_at=None,
        )
    return BankOut(
        bank_name=bank.bank_name,
        account_holder_name=bank.account_holder_name,
        account_number_masked=f"••••{bank.account_last4}" if bank.account_last4 else None,
        account_number=decrypt(bank.account_number_enc)
        if reveal and bank.account_number_enc
        else None,
        ifsc=bank.ifsc,
        branch=bank.branch,
        updated_at=bank.updated_at,
    )


@router.get("/projects/{project_id}/bank", response_model=BankOut)
async def get_bank(
    project_id: int,
    request: Request,
    admin: Admin,
    db: DbSession,
    reveal: Annotated[bool, Query()] = False,
) -> BankOut:
    """Masked by default; reveal=true shows the full account number and is logged."""
    await _project(db, project_id)
    bank = await db.get(ProjectBank, project_id)
    if reveal and bank and bank.account_number_enc:
        log_audit(
            db,
            action="project.bank_revealed",
            entity_type="project",
            entity_id=project_id,
            actor=admin,
            request=request,
        )
        await db.commit()
    return _bank_out(bank, reveal)


@router.put("/projects/{project_id}/bank", response_model=BankOut)
async def put_bank(
    project_id: int, body: BankIn, request: Request, admin: Admin, db: DbSession
) -> BankOut:
    await _project(db, project_id)
    bank = await db.get(ProjectBank, project_id) or ProjectBank(project_id=project_id)
    data = body.model_dump(exclude_unset=True)
    changed = []
    for k in ("bank_name", "account_holder_name", "ifsc", "branch"):
        if k in data and getattr(bank, k, None) != data[k]:
            setattr(bank, k, data[k])
            changed.append(k)
    if data.get("account_number"):
        bank.account_number_enc = encrypt(data["account_number"])
        bank.account_last4 = data["account_number"][-4:]
        changed.append("account_number")
    bank.updated_by_id = admin.id
    db.add(bank)
    if changed:  # never log the account number itself
        log_audit(
            db,
            action="project.bank",
            entity_type="project",
            entity_id=project_id,
            actor=admin,
            details={"changed": changed},
            request=request,
        )
    await db.commit()
    await db.refresh(bank)
    return _bank_out(bank)


@router.get("/projects/{project_id}/doc-readiness", response_model=doc_readiness.Readiness)
async def readiness(project_id: int, _: DocsOrManager, db: DbSession) -> doc_readiness.Readiness:
    return await doc_readiness.check(db, await _project(db, project_id))
