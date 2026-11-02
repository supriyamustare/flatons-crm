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
from app.models.booking import Booking
from app.models.postsales import (
    CaseEvent,
    CaseStatus,
    CoApplicant,
    CustomerProfile,
    KycDocType,
    KycDocument,
    KycStatus,
    OnboardingStatus,
    PostSalesCase,
)
from app.models.project import Project
from app.models.user import CASE_EDITORS, KYC_VIEWERS, POSTSALES_ROLES, Role, User
from app.schemas.postsales import (
    AssignIn,
    CaseDetail,
    CaseEventOut,
    CasePage,
    CaseSummary,
    CoApplicantOut,
    KycDocOut,
    OnboardingAction,
    ProfileIn,
    ProfileOut,
    Reason,
    Requirement,
)
from app.schemas.user import UserBrief
from app.services import postsales as svc
from app.services import receipts as files
from app.services.audit import log_audit
from app.services.notifications import notify

router = APIRouter(prefix="/post-sales", tags=["post-sales"])
Viewer = Annotated[User, Depends(require_role(*POSTSALES_ROLES))]
Editor = Annotated[User, Depends(require_role(*CASE_EDITORS))]
KycViewer = Annotated[User, Depends(require_role(*KYC_VIEWERS))]
Allocator = Annotated[User, Depends(require_role(Role.admin, Role.crm_manager))]
Sales = Annotated[User, Depends(require_role(Role.admin, Role.manager, Role.executive))]
KYC_FOLDER = "kyc"


def _http(msg: str, code: int = status.HTTP_422_UNPROCESSABLE_CONTENT) -> HTTPException:
    return HTTPException(code, msg)


async def _case(db: DbSession, case_id: int) -> PostSalesCase:
    case = await db.get(PostSalesCase, case_id)
    if case is None:
        raise _http("Case not found", status.HTTP_404_NOT_FOUND)
    return case


async def _parts(db: DbSession, case: PostSalesCase):
    profile = await db.get(CustomerProfile, case.id)
    co = list(
        await db.scalars(
            select(CoApplicant)
            .where(CoApplicant.case_id == case.id)
            .order_by(CoApplicant.sort_order, CoApplicant.id)
        )
    )
    docs = list(
        await db.scalars(
            select(KycDocument)
            .where(KycDocument.case_id == case.id)
            .order_by(KycDocument.id.desc())
        )
    )
    return profile, co, docs


def _summary(case: PostSalesCase, reqs: list[dict] | None = None) -> dict:
    b = case.booking
    return dict(
        id=case.id,
        case_code=svc.code(case),
        status=case.status,
        onboarding_status=case.onboarding_status,
        customer=b.customer_name or b.lead.name,
        project=b.project.name,
        unit_no=b.unit.unit_no,
        booking_id=b.id,
        booking_code=f"BKG-{b.id:05d}",
        booking_date=b.booking_date,
        agreed_price=b.agreed_price,
        owner=UserBrief.model_validate(case.owner) if case.owner else None,
        sales_exec=UserBrief.model_validate(b.sales_exec) if b.sales_exec else None,
        created_at=case.created_at,
        kyc_done=sum(1 for r in reqs if r["status"] == "verified") if reqs is not None else 0,
        kyc_total=len(reqs) if reqs is not None else 0,
    )


async def _detail(db: DbSession, case: PostSalesCase, user: User) -> CaseDetail:
    await db.refresh(case)
    profile, co, docs = await _parts(db, case)
    reqs = svc.requirements(profile, co, docs) if profile else []
    project = await db.get(Project, case.booking.project_id)
    history = list(
        await db.scalars(
            select(CaseEvent)
            .where(CaseEvent.case_id == case.id)
            .order_by(CaseEvent.at, CaseEvent.id)
        )
    )
    return CaseDetail(
        **_summary(case, reqs),
        returned_reason=case.returned_reason,
        clarification_reason=case.clarification_reason,
        accepted_at=case.accepted_at,
        handover=svc.handover_checklist(case, project),
        profile=ProfileOut.model_validate(profile) if profile else None,
        co_applicants=[CoApplicantOut.model_validate(c) for c in co],
        requirements=[Requirement(**r) for r in reqs],
        documents=[KycDocOut.model_validate(d) for d in docs],
        profile_problems=svc.profile_problems(profile, co) if profile else [],
        can_edit=user.role in CASE_EDITORS and case.status == CaseStatus.accepted,
        can_view_kyc=user.role in KYC_VIEWERS,
        history=[CaseEventOut.model_validate(e) for e in history],
    )


def _editable(case: PostSalesCase) -> None:
    if case.status != CaseStatus.accepted:
        raise _http(
            "Accept the handover first"
            if case.status == CaseStatus.handover_pending
            else "This case can't be changed now"
        )


# ---------------------------------------------------------------- cases


@router.get("/cases", response_model=CasePage)
async def list_cases(
    user: Viewer,
    db: DbSession,
    case_status: Annotated[CaseStatus | None, Query(alias="status")] = None,
    onboarding: Annotated[OnboardingStatus | None, Query()] = None,
    project_id: Annotated[int | None, Query()] = None,
    owner_id: Annotated[int | None, Query()] = None,
    mine: Annotated[bool, Query()] = False,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
) -> CasePage:
    base = select(PostSalesCase).join(Booking, Booking.id == PostSalesCase.booking_id)
    if project_id:
        base = base.where(Booking.project_id == project_id)
    if mine:
        base = base.where(PostSalesCase.owner_id == user.id)
    elif owner_id:
        base = base.where(PostSalesCase.owner_id == owner_id)
    sub = base.subquery()
    counts = {
        f"status:{k}": n
        for k, n in (
            await db.execute(select(sub.c.status, func.count()).group_by(sub.c.status))
        ).all()
    }
    counts |= {
        f"onboarding:{k}": n
        for k, n in (
            await db.execute(
                select(sub.c.onboarding_status, func.count())
                .where(sub.c.status == CaseStatus.accepted)
                .group_by(sub.c.onboarding_status)
            )
        ).all()
    }
    stmt = base
    if case_status:
        stmt = stmt.where(PostSalesCase.status == case_status)
    if onboarding:
        stmt = stmt.where(PostSalesCase.onboarding_status == onboarding)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    cases = list(
        await db.scalars(
            stmt.order_by(PostSalesCase.created_at.desc(), PostSalesCase.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    )
    items = []
    for c in cases:
        profile, co, docs = await _parts(db, c)
        items.append(
            CaseSummary(**_summary(c, svc.requirements(profile, co, docs) if profile else []))
        )
    return CasePage(items=items, total=total, counts={str(k): v for k, v in counts.items()})


@router.get("/cases/{case_id}", response_model=CaseDetail)
async def get_case(case_id: int, user: Viewer, db: DbSession) -> CaseDetail:
    return await _detail(db, await _case(db, case_id), user)


@router.get("/by-booking/{booking_id}")
async def case_for_booking(
    booking_id: int,
    _: Annotated[User, Depends(require_role(*POSTSALES_ROLES, Role.manager, Role.executive))],
    db: DbSession,
) -> dict:
    """For the booking page: the case's number and statuses only (no KYC or profile)."""
    case = await db.scalar(select(PostSalesCase).where(PostSalesCase.booking_id == booking_id))
    if case is None:
        raise _http("No post-sales case for this booking", status.HTTP_404_NOT_FOUND)
    return {
        "id": case.id,
        "case_code": svc.code(case),
        "status": case.status.value,
        "onboarding_status": case.onboarding_status.value,
        "returned_reason": case.returned_reason,
    }


@router.post("/cases/{case_id}/accept", response_model=CaseDetail)
async def accept(case_id: int, request: Request, user: Editor, db: DbSession) -> CaseDetail:
    case = await _case(db, case_id)
    if case.status != CaseStatus.handover_pending:
        raise _http("Only a pending handover can be accepted")
    project = await db.get(Project, case.booking.project_id)
    missing = [
        c["item"] for c in svc.handover_checklist(case, project) if c["required"] and not c["ok"]
    ]
    if missing:
        raise _http(f"Can't accept yet; missing: {', '.join(missing)}. Return it to sales instead.")
    case.status, case.accepted_by_id, case.accepted_at = CaseStatus.accepted, user.id, svc.now()
    case.onboarding_status = OnboardingStatus.documents_pending
    case.returned_reason = None
    if case.owner_id is None and user.role == Role.postsales_exec:
        case.owner_id = user.id
    svc.event(db, case, "accepted", user)
    log_audit(
        db,
        action="postsales.accept",
        entity_type="postsales_case",
        entity_id=case.id,
        actor=user,
        request=request,
    )
    await db.commit()
    return await _detail(db, case, user)


@router.post("/cases/{case_id}/return", response_model=CaseDetail)
async def return_to_sales(
    case_id: int, body: Reason, request: Request, user: Editor, db: DbSession
) -> CaseDetail:
    case = await _case(db, case_id)
    if case.status != CaseStatus.handover_pending:
        raise _http("Only a pending handover can be returned")
    case.status, case.returned_reason = CaseStatus.returned_to_sales, body.reason
    svc.event(db, case, "returned_to_sales", user, {"reason": body.reason})
    b = case.booking
    recipients = {b.sales_exec_id, b.recorded_by_id} - {None}
    recipients |= set(
        await db.scalars(select(User.id).where(User.is_active.is_(True), User.role == Role.manager))
    )
    for uid in recipients:
        notify(
            db,
            user_id=uid,
            type="handover_returned",
            title=f"Handover returned: {b.lead.name}",
            body=f"Post-sales needs: {body.reason}",
            link=f"/bookings/{b.id}",
        )
    log_audit(
        db,
        action="postsales.return",
        entity_type="postsales_case",
        entity_id=case.id,
        actor=user,
        details={"reason": body.reason},
        request=request,
    )
    await db.commit()
    return await _detail(db, case, user)


@router.post("/cases/{case_id}/resend")
async def resend(case_id: int, request: Request, user: Sales, db: DbSession) -> dict:
    """Sales corrected the booking and sends it back to post-sales."""
    case = await _case(db, case_id)
    if case.status != CaseStatus.returned_to_sales:
        raise _http("Only a returned handover can be resent")
    if user.role == Role.executive and case.booking.sales_exec_id != user.id:
        raise _http(
            "Only the person who handled this booking can resend it", status.HTTP_403_FORBIDDEN
        )
    case.status = CaseStatus.handover_pending
    svc.event(db, case, "resent_by_sales", user, {"previous_reason": case.returned_reason})
    for uid in await db.scalars(
        select(User.id).where(
            User.is_active.is_(True), User.role.in_([Role.crm_manager, Role.postsales_exec])
        )
    ):
        notify(
            db,
            user_id=uid,
            type="handover",
            title=f"Handover resent: {case.booking.lead.name}",
            body="Sales has corrected the booking",
            link=f"/post-sales/{case.id}",
        )
    log_audit(
        db,
        action="postsales.resend",
        entity_type="postsales_case",
        entity_id=case.id,
        actor=user,
        request=request,
    )
    await db.commit()
    return {"status": case.status.value}


@router.post("/cases/{case_id}/assign", response_model=CaseDetail)
async def assign(
    case_id: int, body: AssignIn, request: Request, user: Allocator, db: DbSession
) -> CaseDetail:
    case = await _case(db, case_id)
    owner = await db.get(User, body.owner_id)
    if (
        owner is None
        or not owner.is_active
        or owner.role not in (Role.postsales_exec, Role.crm_manager)
    ):
        raise _http("Choose an active post-sales executive or CRM manager")
    before = case.owner_id
    case.owner_id = owner.id
    svc.event(db, case, "assigned", user, {"from": before, "to": owner.id})
    if owner.id != user.id:
        notify(
            db,
            user_id=owner.id,
            type="case_assigned",
            title=f"Case assigned: {case.booking.lead.name}",
            body=f"{svc.code(case)} is now yours",
            link=f"/post-sales/{case.id}",
        )
    log_audit(
        db,
        action="postsales.assign",
        entity_type="postsales_case",
        entity_id=case.id,
        actor=user,
        details={"owner_id": owner.id},
        request=request,
    )
    await db.commit()
    return await _detail(db, case, user)


# ---------------------------------------------------------------- customer master


@router.put("/cases/{case_id}/profile", response_model=CaseDetail)
async def save_profile(
    case_id: int, body: ProfileIn, request: Request, user: Editor, db: DbSession
) -> CaseDetail:
    case = await _case(db, case_id)
    _editable(case)
    profile, co, docs = await _parts(db, case)
    profile = profile or CustomerProfile(case_id=case.id)
    data = body.model_dump(
        exclude={"co_applicants", "consent_portal", "consent_electronic", "consent_data"}
    )
    before = {
        k: str(getattr(profile, k, None))
        for k in ("legal_name", "pan", "ownership_type", "entity_name", "date_of_birth")
    }
    for k, v in data.items():
        setattr(profile, k, v)
    now = svc.now()
    for flag, col in (
        ("consent_portal", "consent_portal_at"),
        ("consent_electronic", "consent_electronic_at"),
        ("consent_data", "consent_data_at"),
    ):
        given = getattr(body, flag)
        if given and not getattr(profile, col):
            setattr(profile, col, now)
        elif not given:
            setattr(profile, col, None)
    db.add(profile)
    # Co-applicants: keep the ones sent with an id, add new ones, remove the rest (only if they have no KYC)
    existing = {c.id: c for c in co}
    keep = set()
    for i, c in enumerate(body.co_applicants):
        row = existing.get(c.id) if c.id else None
        if c.id and row is None:
            raise _http("That co-applicant isn't on this case")
        row = row or CoApplicant(case_id=case.id)
        for k, v in c.model_dump(exclude={"id"}).items():
            setattr(row, k, v)
        row.sort_order = i
        db.add(row)
        if c.id:
            keep.add(c.id)
    for cid, row in existing.items():
        if cid not in keep:
            if any(d.co_applicant_id == cid for d in docs):
                raise _http(f"{row.name} has KYC documents and can't be removed")
            await db.delete(row)
    await db.flush()
    after = {k: str(getattr(profile, k, None)) for k in before}
    changed = {k: {"from": before[k], "to": after[k]} for k in before if before[k] != after[k]}
    # Changing who the buyer is after approval sends KYC back for review
    if case.onboarding_status == OnboardingStatus.approved and changed:
        case.onboarding_status = OnboardingStatus.under_review
        svc.event(
            db,
            case,
            "approval_reopened",
            user,
            {"reason": "Customer identity details changed", "changed": changed},
        )
    svc.event(db, case, "profile_saved", user, {"changed": changed} if changed else None)
    log_audit(
        db,
        action="postsales.profile",
        entity_type="postsales_case",
        entity_id=case.id,
        actor=user,
        details={"changed": changed},
        request=request,
    )
    await db.commit()
    return await _detail(db, case, user)


# ---------------------------------------------------------------- KYC


@router.post("/cases/{case_id}/kyc", response_model=CaseDetail, status_code=status.HTTP_201_CREATED)
async def upload_kyc(
    case_id: int,
    request: Request,
    user: Editor,
    db: DbSession,
    doc_type: Annotated[KycDocType, Form()],
    file: Annotated[UploadFile, File()],
    co_applicant_id: Annotated[int | None, Form()] = None,
    expiry_date: Annotated[date | None, Form()] = None,
) -> CaseDetail:
    case = await _case(db, case_id)
    _editable(case)
    if (
        co_applicant_id
        and (await db.get(CoApplicant, co_applicant_id) or CoApplicant(case_id=-1)).case_id
        != case.id
    ):
        raise _http("That co-applicant isn't on this case")
    if expiry_date and expiry_date < date.today():
        raise _http("That document has already expired")
    data = await file.read()
    await file.seek(0)
    try:
        stored, name, mime = await files.save_receipt(
            file, folder=KYC_FOLDER, max_mb=10, what="KYC documents"
        )
    except files.ReceiptError as exc:
        raise _http(str(exc)) from None
    digest = svc.sha256(data)
    dup = await db.scalar(
        select(KycDocument.id).where(
            KycDocument.case_id == case.id,
            KycDocument.sha256 == digest,
            KycDocument.status != KycStatus.superseded,
        )
    )
    if dup:
        files.delete_receipt(stored, KYC_FOLDER)
        raise _http("This exact file is already uploaded on this case", status.HTTP_409_CONFLICT)
    doc = KycDocument(
        case_id=case.id,
        co_applicant_id=co_applicant_id,
        doc_type=doc_type,
        file_path=stored,
        file_name=name,
        file_type=mime,
        sha256=digest,
        expiry_date=expiry_date,
        uploaded_by_id=user.id,
    )
    db.add(doc)
    await db.flush()
    for old in await db.scalars(
        select(KycDocument).where(
            KycDocument.case_id == case.id,
            KycDocument.doc_type == doc_type,
            KycDocument.id != doc.id,
            KycDocument.co_applicant_id.is_(None)
            if co_applicant_id is None
            else KycDocument.co_applicant_id == co_applicant_id,
            KycDocument.status != KycStatus.superseded,
        )
    ):
        old.status, old.superseded_by_id = KycStatus.superseded, doc.id
    svc.event(
        db,
        case,
        "kyc_uploaded",
        user,
        {"doc_type": doc_type.value, "document_id": doc.id, "co_applicant_id": co_applicant_id},
    )
    # Once every requirement has a document, it goes for review
    profile, co, docs = await _parts(db, case)
    reqs = svc.requirements(profile, co, docs)
    if case.onboarding_status in (
        OnboardingStatus.documents_pending,
        OnboardingStatus.clarification_required,
    ) and all(r["status"] in ("pending", "verified") for r in reqs):
        case.onboarding_status = OnboardingStatus.under_review
        svc.event(
            db, case, "onboarding_under_review", None, {"reason": "All required documents uploaded"}
        )
    log_audit(
        db,
        action="kyc.upload",
        entity_type="kyc_document",
        entity_id=doc.id,
        actor=user,
        details={"case_id": case.id, "doc_type": doc_type.value},
        request=request,
    )
    await db.commit()
    return await _detail(db, case, user)


async def _doc(db: DbSession, doc_id: int) -> KycDocument:
    doc = await db.get(KycDocument, doc_id)
    if doc is None:
        raise _http("Document not found", status.HTTP_404_NOT_FOUND)
    return doc


@router.get("/kyc/{doc_id}/file")
async def kyc_file(doc_id: int, request: Request, user: KycViewer, db: DbSession) -> FileResponse:
    doc = await _doc(db, doc_id)
    path = files.receipt_file(doc.file_path, KYC_FOLDER)
    if not path.exists():
        raise _http("The file is missing", status.HTTP_404_NOT_FOUND)
    log_audit(
        db,
        action="kyc.viewed",
        entity_type="kyc_document",
        entity_id=doc.id,
        actor=user,
        request=request,
    )
    await db.commit()
    return FileResponse(
        path,
        media_type=doc.file_type,
        headers={
            "Content-Disposition": f'inline; filename="{doc.file_name}"',
            "Cache-Control": "private, no-store",
        },
    )


async def _review(db: DbSession, doc_id: int, user: User) -> tuple[KycDocument, PostSalesCase]:
    doc = await _doc(db, doc_id)
    case = await _case(db, doc.case_id)
    _editable(case)
    if doc.status != KycStatus.pending:
        raise _http("Only a document waiting for review can be verified or rejected")
    if doc.uploaded_by_id == user.id and user.role != Role.admin:
        raise _http(
            "Someone other than the uploader must review this document", status.HTTP_403_FORBIDDEN
        )
    return doc, case


@router.post("/kyc/{doc_id}/verify", response_model=CaseDetail)
async def verify_kyc(doc_id: int, request: Request, user: Editor, db: DbSession) -> CaseDetail:
    doc, case = await _review(db, doc_id, user)
    doc.status, doc.reviewed_by_id, doc.reviewed_at = KycStatus.verified, user.id, svc.now()
    svc.event(
        db, case, "kyc_verified", user, {"document_id": doc.id, "doc_type": doc.doc_type.value}
    )
    log_audit(
        db,
        action="kyc.verify",
        entity_type="kyc_document",
        entity_id=doc.id,
        actor=user,
        request=request,
    )
    await db.commit()
    return await _detail(db, case, user)


@router.post("/kyc/{doc_id}/reject", response_model=CaseDetail)
async def reject_kyc(
    doc_id: int, body: Reason, request: Request, user: Editor, db: DbSession
) -> CaseDetail:
    doc, case = await _review(db, doc_id, user)
    doc.status, doc.reviewed_by_id, doc.reviewed_at, doc.review_note = (
        KycStatus.rejected,
        user.id,
        svc.now(),
        body.reason,
    )
    if case.onboarding_status in (
        OnboardingStatus.under_review,
        OnboardingStatus.documents_pending,
    ):
        case.onboarding_status, case.clarification_reason = (
            OnboardingStatus.clarification_required,
            body.reason,
        )
    svc.event(
        db,
        case,
        "kyc_rejected",
        user,
        {"document_id": doc.id, "doc_type": doc.doc_type.value, "reason": body.reason},
    )
    log_audit(
        db,
        action="kyc.reject",
        entity_type="kyc_document",
        entity_id=doc.id,
        actor=user,
        details={"reason": body.reason},
        request=request,
    )
    await db.commit()
    return await _detail(db, case, user)


@router.post("/cases/{case_id}/onboarding", response_model=CaseDetail)
async def onboarding(
    case_id: int, body: OnboardingAction, request: Request, user: Editor, db: DbSession
) -> CaseDetail:
    case = await _case(db, case_id)
    _editable(case)
    profile, co, docs = await _parts(db, case)
    reqs = svc.requirements(profile, co, docs)
    s = case.onboarding_status
    if body.action == "submit_for_review":
        if s not in (OnboardingStatus.documents_pending, OnboardingStatus.clarification_required):
            raise _http("Only pending or clarification cases can be submitted for review")
        missing = [
            f"{r['applicant']}: {r['label']}"
            for r in reqs
            if r["status"] not in ("pending", "verified")
        ]
        if missing:
            raise _http("Still missing: " + "; ".join(missing))
        case.onboarding_status = OnboardingStatus.under_review
    elif body.action == "request_clarification":
        if s != OnboardingStatus.under_review:
            raise _http("Clarification can only be requested during review")
        if not body.reason:
            raise _http("Give a reason for the clarification")
        case.onboarding_status, case.clarification_reason = (
            OnboardingStatus.clarification_required,
            body.reason,
        )
    else:  # approve
        if s != OnboardingStatus.under_review:
            raise _http("Only a case under review can be approved")
        unverified = [f"{r['applicant']}: {r['label']}" for r in reqs if r["status"] != "verified"]
        problems = svc.profile_problems(profile, co)
        if unverified or problems:
            raise _http("Can't approve yet: " + "; ".join(unverified + problems))
        case.onboarding_status, case.clarification_reason = OnboardingStatus.approved, None
    svc.event(
        db,
        case,
        f"onboarding_{case.onboarding_status.value}",
        user,
        {"reason": body.reason} if body.reason else None,
    )
    log_audit(
        db,
        action="postsales.onboarding",
        entity_type="postsales_case",
        entity_id=case.id,
        actor=user,
        details={"action": body.action, "to": case.onboarding_status.value, "reason": body.reason},
        request=request,
    )
    await db.commit()
    return await _detail(db, case, user)
