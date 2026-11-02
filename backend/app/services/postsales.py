"""Post-sales rules: handover from sales, the customer master, KYC requirements and onboarding."""

import hashlib
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.booking import Booking
from app.models.postsales import (
    ENTITY_OWNERSHIP,
    CaseEvent,
    CaseStatus,
    CoApplicant,
    CustomerProfile,
    KycDocType,
    KycDocument,
    KycStatus,
    OnboardingStatus,
    OwnershipType,
    PostSalesCase,
)
from app.models.project import Project
from app.models.user import Role, User
from app.services.cost_sheet import merged
from app.services.notifications import notify


class CaseRuleError(ValueError):
    """Broken rule; shown to the user."""


def code(case: PostSalesCase) -> str:
    return f"PSC-{case.id:05d}"


def event(
    db: AsyncSession,
    case: PostSalesCase,
    action: str,
    actor: User | None,
    details: dict | None = None,
) -> None:
    db.add(
        CaseEvent(
            case_id=case.id, action=action, actor_id=actor.id if actor else None, details=details
        )
    )


async def create_for_booking(
    db: AsyncSession, booking: Booking, actor: User | None
) -> PostSalesCase:
    """Called when a booking is recorded: the post-sales case and customer profile, filled from the booking."""
    case = PostSalesCase(
        booking_id=booking.id,
        status=CaseStatus.handover_pending,
        onboarding_status=OnboardingStatus.not_started,
    )
    db.add(case)
    await db.flush()
    lead = booking.lead
    db.add(
        CustomerProfile(
            case_id=case.id,
            ownership_type=OwnershipType.individual,
            legal_name=booking.customer_name or lead.name,
            mobile=booking.customer_mobile or lead.mobile,
            email=booking.customer_email or lead.email,
            correspondence_address=booking.customer_address,
        )
    )
    event(db, case, "created", actor, {"booking_id": booking.id})
    for uid in await db.scalars(
        select(User.id).where(
            User.is_active.is_(True), User.role.in_([Role.crm_manager, Role.postsales_exec])
        )
    ):
        notify(
            db,
            user_id=uid,
            type="handover",
            title=f"New handover: {lead.name}",
            body=f"Booking {booking.id:05d} is ready for post-sales to check and accept",
            link=f"/post-sales/{case.id}",
        )
    return case


def handover_checklist(case: PostSalesCase, project: Project) -> list[dict]:
    """What post-sales needs from sales. `required` items must be present before accepting."""
    b = case.booking
    stages = merged(project.cost_sheet, None)["stages"] if project.cost_sheet else []
    plan_ok = bool(project.cost_sheet) and round(sum(float(s["pct"]) for s in stages), 4) == 100
    return [
        {"item": "Customer name", "ok": bool(b.customer_name or b.lead.name), "required": True},
        {"item": "Mobile number", "ok": bool(b.customer_mobile or b.lead.mobile), "required": True},
        {"item": "Email", "ok": bool(b.customer_email or b.lead.email), "required": False},
        {"item": "Address", "ok": bool(b.customer_address), "required": False},
        {"item": "Unit", "ok": b.unit_id is not None, "required": True},
        {"item": "Agreed price", "ok": b.agreed_price > 0, "required": True},
        {"item": "Booking amount received", "ok": b.booking_amount > 0, "required": False},
        {"item": "Payment plan (project payment stages)", "ok": plan_ok, "required": True},
        {"item": "Salesperson", "ok": b.sales_exec_id is not None, "required": False},
    ]


# ---------------------------------------------------------------- KYC requirements

ID_PROOFS = (
    KycDocType.aadhaar,
    KycDocType.passport,
    KycDocType.voter_id,
    KycDocType.driving_licence,
)
PERSON_REQUIREMENTS = [
    ("pan", "PAN card", (KycDocType.pan,)),
    ("identity", "Identity proof (Aadhaar, passport, voter ID or driving licence)", ID_PROOFS),
    ("address", "Address proof", (*ID_PROOFS, KycDocType.address_proof)),
    ("photo", "Photograph", (KycDocType.photo,)),
]
ENTITY_REQUIREMENTS = [
    ("entity_pan", "PAN card of the entity", (KycDocType.entity_pan,)),
    ("registration", "Registration certificate or deed", (KycDocType.registration_certificate,)),
    ("authority", "Board resolution or authority letter", (KycDocType.board_resolution,)),
]


def requirements(
    profile: CustomerProfile, co_applicants: list[CoApplicant], docs: list[KycDocument]
) -> list[dict]:
    """Each requirement, for whom, and the best current document for it (verified > pending > rejected)."""
    live = [d for d in docs if d.status != KycStatus.superseded]
    rank = {
        KycStatus.verified: 0,
        KycStatus.pending: 1,
        KycStatus.rejected: 2,
        KycStatus.expired: 3,
    }
    people = [(None, profile.legal_name or "Primary applicant")] + [
        (c.id, c.name) for c in co_applicants
    ]
    out = []

    def add(applicant_id, who, key, label, types):
        matches = sorted(
            (d for d in live if d.co_applicant_id == applicant_id and d.doc_type in types),
            key=lambda d: (rank[d.status], -d.id),
        )
        best = matches[0] if matches else None
        out.append(
            {
                "applicant_id": applicant_id,
                "applicant": who,
                "key": key,
                "label": label,
                "accepted_types": [t.value for t in types],
                "status": best.status.value if best else "missing",
                "document_id": best.id if best else None,
            }
        )

    if profile.ownership_type in ENTITY_OWNERSHIP:
        for key, label, types in ENTITY_REQUIREMENTS:
            add(None, profile.entity_name or "Entity", key, label, types)
        signatory = profile.legal_name or "Authorized signatory"
        for key, label, types in PERSON_REQUIREMENTS:
            add(None, signatory, key, label, types)
    else:
        for applicant_id, who in people:
            for key, label, types in PERSON_REQUIREMENTS:
                add(applicant_id, who, key, label, types)
    return out


def profile_problems(profile: CustomerProfile, co_applicants: list[CoApplicant]) -> list[str]:
    """What stops onboarding approval in the customer details themselves."""
    problems = []
    if not profile.legal_name:
        problems.append("Legal name")
    if not profile.pan:
        problems.append("PAN")
    if not profile.correspondence_address:
        problems.append("Correspondence address")
    if profile.ownership_type in ENTITY_OWNERSHIP and not profile.entity_name:
        problems.append("Entity name")
    if profile.ownership_type == OwnershipType.joint:
        if not co_applicants:
            problems.append("At least one co-applicant for joint ownership")
        shares = [profile.ownership_pct, *[c.ownership_pct for c in co_applicants]]
        if any(s is None for s in shares) or sum(shares) != Decimal(100):
            problems.append("Ownership shares must add up to 100%")
    if not profile.consent_data_at:
        problems.append("Consent for data processing")
    return problems


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def now() -> datetime:
    return datetime.now(UTC)
