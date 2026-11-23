from datetime import UTC, date, datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, StringConstraints
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.core.deps import DbSession, require_role
from app.models.case_document import Approval, CaseDocument, DocCategory, Verification, Visibility
from app.models.postsales import CaseStatus, PostSalesCase
from app.models.user import POSTSALES_ROLES, User
from app.schemas.common import PlainText
from app.schemas.user import UserBrief
from app.services import case_documents as rules
from app.services import postsales as cases
from app.services import receipts as files
from app.services.audit import log_audit

router = APIRouter(prefix="/post-sales", tags=["customer documents"])
Staff = Annotated[User, Depends(require_role(*POSTSALES_ROLES))]
IST = timezone(timedelta(hours=5, minutes=30))
FOLDER = "case_docs"


def today() -> date:
    return datetime.now(UTC).astimezone(IST).date()


class ReasonIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: Annotated[PlainText, StringConstraints(min_length=3, max_length=500)]


class DocOut(BaseModel):
    id: int
    doc_no: str
    category: DocCategory
    doc_type: str
    title: str
    doc_number: str | None
    doc_date: date | None
    expiry_date: date | None
    linked_ref: str | None
    file_name: str
    file_type: str
    file_size: int
    sha256: str
    verification: str  # pending / verified / rejected / expired
    approval: Approval
    visibility: Visibility
    status_reason: str | None
    version: int
    supersedes: str | None
    superseded: bool
    version_reason: str | None
    uploaded_by: UserBrief | None
    uploaded_at: datetime
    reviewed_by: UserBrief | None
    reviewed_at: datetime | None
    released_at: datetime | None
    url: str
    can_review: bool = False
    can_release: bool = False
    can_withdraw: bool = False
    can_replace: bool = False


class FolderOut(BaseModel):
    categories: list[dict]  # {"key", "label", "count", "can_upload"}
    documents: list[DocOut]  # newest first, all versions (superseded ones flagged)
    system: list[dict]  # documents the CRM generated or already holds


def code(d: CaseDocument) -> str:
    return f"DOC-{d.id:05d}"


async def _case(db: DbSession, case_id: int) -> PostSalesCase:
    case = await db.get(PostSalesCase, case_id)
    if case is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Case not found")
    return case


async def _doc(db: DbSession, did: int, user: User) -> CaseDocument:
    d = await db.get(CaseDocument, did)
    if d is None or user.role not in rules.VIEW[d.category]:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    return d


def _log(
    db: DbSession,
    case: PostSalesCase,
    user: User,
    action: str,
    d: CaseDocument,
    request: Request,
    extra: dict | None = None,
) -> None:
    details = {"document": code(d), "category": d.category.value, "title": d.title, **(extra or {})}
    cases.event(db, case, action, user, details)
    log_audit(
        db,
        action=action.replace("document_", "document."),
        entity_type="case_document",
        entity_id=d.id,
        actor=user,
        details=details,
        request=request,
    )


async def folder(db: DbSession, case: PostSalesCase, user: User) -> FolderOut:
    rows = [
        d
        for d in await db.scalars(
            select(CaseDocument)
            .where(CaseDocument.case_id == case.id)
            .order_by(CaseDocument.uploaded_at.desc(), CaseDocument.id.desc())
        )
        if user.role in rules.VIEW[d.category]
    ]
    ids = {x for d in rows for x in (d.uploaded_by_id, d.reviewed_by_id) if x}
    users = {u.id: u for u in await db.scalars(select(User).where(User.id.in_(ids)))} if ids else {}
    brief = lambda uid: UserBrief.model_validate(users[uid]) if uid in users else None  # noqa: E731
    codes = {d.id: code(d) for d in rows}
    t = today()
    docs = []
    for d in rows:
        live = d.superseded_by_id is None
        ver = (
            "expired"
            if d.expiry_date and d.expiry_date < t and d.verification == Verification.verified
            else d.verification.value
        )
        docs.append(
            DocOut(
                id=d.id,
                doc_no=codes[d.id],
                category=d.category,
                doc_type=d.doc_type,
                title=d.title,
                doc_number=d.doc_number,
                doc_date=d.doc_date,
                expiry_date=d.expiry_date,
                linked_ref=d.linked_ref,
                file_name=d.file_name,
                file_type=d.file_type,
                file_size=d.file_size,
                sha256=d.sha256,
                verification=ver,
                approval=d.approval,
                visibility=d.visibility,
                status_reason=d.status_reason,
                version=d.version,
                supersedes=codes.get(d.supersedes_id) if d.supersedes_id else None,
                superseded=not live,
                version_reason=d.version_reason,
                uploaded_by=brief(d.uploaded_by_id),
                uploaded_at=d.uploaded_at,
                reviewed_by=brief(d.reviewed_by_id),
                reviewed_at=d.reviewed_at,
                released_at=d.released_at,
                url=f"/api/post-sales/documents/{d.id}/file",
                can_review=live
                and d.approval == Approval.under_approval
                and user.role in rules.REVIEW[d.category]
                and d.uploaded_by_id != user.id,
                can_release=live and d.approval == Approval.approved and user.role in rules.RELEASE,
                can_withdraw=live
                and d.approval in (Approval.approved, Approval.released)
                and user.role in rules.RELEASE,
                can_replace=live
                and d.approval != Approval.withdrawn
                and user.role in rules.UPLOAD[d.category]
                and case.status == CaseStatus.accepted,
            )
        )
    counts = {c: sum(1 for d in docs if d.category == c and not d.superseded) for c in DocCategory}
    system = await rules.system_documents(db, case.id, user.role)
    for s in system:
        counts[s["category"]] += 1
    cats = [
        {
            "key": c.value,
            "label": rules.LABELS[c],
            "count": counts[c],
            "can_upload": user.role in rules.UPLOAD[c] and case.status == CaseStatus.accepted,
        }
        for c in DocCategory
        if user.role in rules.VIEW[c]
    ]
    return FolderOut(
        categories=cats,
        documents=docs,
        system=[{**s, "category": s["category"].value} for s in system],
    )


@router.get("/cases/{case_id}/documents", response_model=FolderOut)
async def get_folder(case_id: int, user: Staff, db: DbSession) -> FolderOut:
    return await folder(db, await _case(db, case_id), user)


@router.post(
    "/cases/{case_id}/documents", response_model=FolderOut, status_code=status.HTTP_201_CREATED
)
async def upload(
    case_id: int,
    request: Request,
    user: Staff,
    db: DbSession,
    category: Annotated[DocCategory, Form()],
    doc_type: Annotated[str, Form(min_length=2, max_length=120)],
    title: Annotated[str, Form(min_length=2, max_length=200)],
    file: Annotated[UploadFile, File()],
    doc_number: Annotated[str | None, Form(max_length=80)] = None,
    doc_date: Annotated[date | None, Form()] = None,
    expiry_date: Annotated[date | None, Form()] = None,
    linked_ref: Annotated[str | None, Form(max_length=80)] = None,
    replaces_id: Annotated[int | None, Form()] = None,
    version_reason: Annotated[str | None, Form(max_length=500)] = None,
) -> FolderOut:
    """Upload a document (or a new version of one, with a reason). It goes for review before it counts as approved."""
    case = await _case(db, case_id)
    if case.status != CaseStatus.accepted:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Documents are added once the handover is accepted",
        )
    if user.role not in rules.UPLOAD[category]:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, f"You can't upload to {rules.LABELS[category]}"
        )
    for v in (doc_type, title, doc_number, linked_ref, version_reason):
        if v and ("<" in v or ">" in v):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Text can't contain < or >")
    if doc_date and doc_date > today():
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "The document date can't be in the future"
        )
    if expiry_date and doc_date and expiry_date < doc_date:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "The expiry date can't be before the document date",
        )
    old = None
    if replaces_id is not None:
        old = await _doc(db, replaces_id, user)
        if old.case_id != case.id or old.superseded_by_id is not None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "Only the latest version of a document on this case can be replaced",
            )
        if old.category != category:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, "A new version stays in the same category"
            )
        if not (version_reason or "").strip() or len(version_reason.strip()) < 3:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, "Give the reason for the new version"
            )
    data = await file.read()
    await file.seek(0)
    digest = cases.sha256(data)
    if await db.scalar(
        select(CaseDocument.id).where(
            CaseDocument.case_id == case.id, CaseDocument.sha256 == digest
        )
    ):
        raise HTTPException(
            status.HTTP_409_CONFLICT, "This exact file is already in the customer's folder"
        )
    number = (doc_number or "").strip() or None
    if number and await db.scalar(
        select(CaseDocument.id).where(
            CaseDocument.case_id == case.id,
            CaseDocument.category == category,
            func.upper(CaseDocument.doc_number) == number.upper(),
            CaseDocument.superseded_by_id.is_(None),
            CaseDocument.approval.notin_([Approval.rejected, Approval.withdrawn]),
            CaseDocument.id != (old.id if old else 0),
        )
    ):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Document number {number} is already in {rules.LABELS[category]}",
        )
    try:
        stored, name, mime = await files.save_receipt(
            file, folder=FOLDER, max_mb=20, what="Documents"
        )
    except files.ReceiptError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
    d = CaseDocument(
        case_id=case.id,
        category=category,
        doc_type=doc_type.strip(),
        title=title.strip(),
        doc_number=None if old else number,  # set after the old version is marked replaced
        doc_date=doc_date,
        expiry_date=expiry_date,
        linked_ref=(linked_ref or "").strip() or None,
        file_path=stored,
        file_name=name,
        file_type=mime,
        file_size=len(data),
        sha256=digest,
        uploaded_by_id=user.id,
        version=old.version + 1 if old else 1,
        supersedes_id=old.id if old else None,
        version_reason=version_reason.strip() if old else None,
    )
    db.add(d)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        files.delete_receipt(stored, FOLDER)
        raise HTTPException(
            status.HTTP_409_CONFLICT, "This file or document number is already in the folder"
        ) from None
    if old:
        old.superseded_by_id = d.id
        await db.flush()
        d.doc_number = number
        if (
            old.approval == Approval.released
        ):  # the customer stops seeing the old version once replaced
            old.approval, old.visibility, old.status_reason = (
                Approval.withdrawn,
                Visibility.internal,
                f"Replaced by {code(d)}: {version_reason.strip()}",
            )
    _log(
        db,
        case,
        user,
        "document_replaced" if old else "document_uploaded",
        d,
        request,
        {"version": d.version, "reason": d.version_reason} if old else None,
    )
    await db.commit()
    return await folder(db, case, user)


async def _review_target(db: DbSession, did: int, user: User) -> tuple[CaseDocument, PostSalesCase]:
    d = await _doc(db, did, user)
    case = await _case(db, d.case_id)
    if d.superseded_by_id is not None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "This version has been replaced")
    return d, case


@router.post("/documents/{did}/approve", response_model=FolderOut)
async def approve(did: int, request: Request, user: Staff, db: DbSession) -> FolderOut:
    d, case = await _review_target(db, did, user)
    if user.role not in rules.REVIEW[d.category]:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, f"You can't review {rules.LABELS[d.category]}"
        )
    if d.approval != Approval.under_approval:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "Only a document under approval can be approved"
        )
    if d.uploaded_by_id == user.id:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Someone other than the uploader must review this document"
        )
    d.verification, d.approval, d.reviewed_by_id, d.reviewed_at = (
        Verification.verified,
        Approval.approved,
        user.id,
        datetime.now(UTC),
    )
    _log(db, case, user, "document_approved", d, request)
    await db.commit()
    return await folder(db, case, user)


@router.post("/documents/{did}/reject", response_model=FolderOut)
async def reject(
    did: int, body: ReasonIn, request: Request, user: Staff, db: DbSession
) -> FolderOut:
    d, case = await _review_target(db, did, user)
    if user.role not in rules.REVIEW[d.category]:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, f"You can't review {rules.LABELS[d.category]}"
        )
    if d.approval != Approval.under_approval:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "Only a document under approval can be rejected"
        )
    if d.uploaded_by_id == user.id:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Someone other than the uploader must review this document"
        )
    d.verification, d.approval, d.status_reason, d.reviewed_by_id, d.reviewed_at = (
        Verification.rejected,
        Approval.rejected,
        body.reason,
        user.id,
        datetime.now(UTC),
    )
    _log(db, case, user, "document_rejected", d, request, {"reason": body.reason})
    await db.commit()
    return await folder(db, case, user)


@router.post("/documents/{did}/release", response_model=FolderOut)
async def release(did: int, request: Request, user: Staff, db: DbSession) -> FolderOut:
    """Make an approved document available to the customer (in the portal, when it opens)."""
    d, case = await _review_target(db, did, user)
    if user.role not in rules.RELEASE:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Only a CRM manager or admin can release documents to the customer",
        )
    if d.approval != Approval.approved:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "Only an approved document can be released"
        )
    if d.expiry_date and d.expiry_date < today():
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "This document has expired; upload a current version",
        )
    d.approval, d.visibility, d.released_by_id, d.released_at = (
        Approval.released,
        Visibility.customer,
        user.id,
        datetime.now(UTC),
    )
    _log(db, case, user, "document_released", d, request)
    from app.services import comms

    if str(getattr(d.visibility, "value", d.visibility)) == "customer":
        await comms.emit(db, "document_released", case, {"document": d.title}, d.id)
    await db.commit()
    return await folder(db, case, user)


@router.post("/documents/{did}/withdraw", response_model=FolderOut)
async def withdraw(
    did: int, body: ReasonIn, request: Request, user: Staff, db: DbSession
) -> FolderOut:
    d, case = await _review_target(db, did, user)
    if user.role not in rules.RELEASE:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Only a CRM manager or admin can withdraw documents"
        )
    if d.approval not in (Approval.approved, Approval.released):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Only an approved or released document can be withdrawn",
        )
    d.approval, d.visibility, d.status_reason = Approval.withdrawn, Visibility.internal, body.reason
    _log(db, case, user, "document_withdrawn", d, request, {"reason": body.reason})
    await db.commit()
    return await folder(db, case, user)


@router.get("/documents/{did}/file")
async def download(did: int, request: Request, user: Staff, db: DbSession) -> FileResponse:
    d = await _doc(db, did, user)
    path = files.receipt_file(d.file_path, FOLDER)
    if not path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "The file is missing")
    log_audit(
        db,
        action="document.downloaded",
        entity_type="case_document",
        entity_id=d.id,
        actor=user,
        request=request,
    )
    await db.commit()
    return FileResponse(
        path,
        media_type=d.file_type,
        headers={
            "Content-Disposition": f'inline; filename="{d.file_name}"',
            "Cache-Control": "private, no-store",
        },
    )
