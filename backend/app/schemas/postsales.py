from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from app.models.postsales import CaseStatus, KycDocType, KycStatus, OnboardingStatus, OwnershipType
from app.schemas.common import LongText, PlainText
from app.schemas.ids import PAN
from app.schemas.user import UserBrief

Name = Annotated[PlainText, StringConstraints(max_length=200)]
Pan = PAN
Phone = Annotated[PlainText, StringConstraints(max_length=20, pattern=r"^[0-9+()\- ]{6,20}$")]
Email = Annotated[
    PlainText, StringConstraints(max_length=254, pattern=r"^[^@\s<>]+@[^@\s<>]+\.[^@\s<>]+$")
]
Pct = Annotated[Decimal, Field(gt=0, le=100, max_digits=5, decimal_places=2)]


def _blank(v):
    return None if isinstance(v, str) and not v.strip() else v


class CoApplicantIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Name
    relation: Annotated[PlainText, StringConstraints(max_length=60)] | None = None
    date_of_birth: date | None = None
    pan: Pan | None = None
    mobile: Phone | None = None
    email: Email | None = None
    ownership_pct: Pct | None = None
    id: int | None = None  # keep the same co-applicant (and their KYC) when editing

    _b = field_validator("relation", "mobile", "email", mode="before")(lambda v: _blank(v))


class ProfileIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ownership_type: OwnershipType
    legal_name: Name | None = None
    entity_name: Name | None = None
    date_of_birth: date | None = None
    pan: Pan | None = None
    ownership_pct: Pct | None = None
    mobile: Phone | None = None
    email: Email | None = None
    correspondence_address: LongText | None = None
    permanent_address: LongText | None = None
    preferred_language: Annotated[PlainText, StringConstraints(max_length=40)] | None = None
    contact_email: bool = True
    contact_sms: bool = True
    contact_whatsapp: bool = False
    communication_needs: Annotated[PlainText, StringConstraints(max_length=300)] | None = None
    consent_portal: bool = False
    consent_electronic: bool = False
    consent_data: bool = False
    nominee_name: Annotated[PlainText, StringConstraints(max_length=150)] | None = None
    nominee_relation: Annotated[PlainText, StringConstraints(max_length=60)] | None = None
    nominee_mobile: Phone | None = None
    co_applicants: Annotated[list[CoApplicantIn], Field(max_length=6)] = []

    _b = field_validator(
        "legal_name",
        "entity_name",
        "mobile",
        "email",
        "correspondence_address",
        "permanent_address",
        "preferred_language",
        "communication_needs",
        "nominee_name",
        "nominee_relation",
        "nominee_mobile",
        mode="before",
    )(lambda v: _blank(v))


class ProfileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    ownership_type: OwnershipType
    legal_name: str | None
    entity_name: str | None
    date_of_birth: date | None
    pan: str | None
    ownership_pct: Decimal | None
    mobile: str | None
    email: str | None
    correspondence_address: str | None
    permanent_address: str | None
    preferred_language: str | None
    contact_email: bool
    contact_sms: bool
    contact_whatsapp: bool
    communication_needs: str | None
    consent_portal_at: datetime | None
    consent_electronic_at: datetime | None
    consent_data_at: datetime | None
    nominee_name: str | None
    nominee_relation: str | None
    nominee_mobile: str | None


class CoApplicantOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    relation: str | None
    date_of_birth: date | None
    pan: str | None
    mobile: str | None
    email: str | None
    ownership_pct: Decimal | None


class KycDocOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    co_applicant_id: int | None
    doc_type: KycDocType
    status: KycStatus
    file_name: str
    file_type: str
    expiry_date: date | None
    review_note: str | None
    uploaded_at: datetime
    uploaded_by_id: int | None
    reviewed_at: datetime | None
    superseded_by_id: int | None


class Requirement(BaseModel):
    applicant_id: int | None
    applicant: str
    key: str
    label: str
    accepted_types: list[KycDocType]
    status: Literal["missing", "pending", "verified", "rejected", "expired"]
    document_id: int | None


class ChecklistItem(BaseModel):
    item: str
    ok: bool
    required: bool


class CaseEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    at: datetime
    action: str
    actor: UserBrief | None
    details: dict | None


class CaseSummary(BaseModel):
    id: int
    case_code: str
    status: CaseStatus
    onboarding_status: OnboardingStatus
    customer: str
    project: str
    unit_no: str
    booking_id: int
    booking_code: str
    booking_date: date
    agreed_price: int
    owner: UserBrief | None
    sales_exec: UserBrief | None
    created_at: datetime
    kyc_done: int = 0
    kyc_total: int = 0


class CaseDetail(CaseSummary):
    returned_reason: str | None
    clarification_reason: str | None
    accepted_at: datetime | None
    handover: list[ChecklistItem]
    profile: ProfileOut | None
    co_applicants: list[CoApplicantOut]
    requirements: list[Requirement]
    documents: list[KycDocOut]  # every upload including superseded and rejected, newest first
    profile_problems: list[str]
    can_edit: bool
    can_view_kyc: bool
    history: list[CaseEventOut]


class CasePage(BaseModel):
    items: list[CaseSummary]
    total: int
    counts: dict[str, int]  # by case status and onboarding status


class Reason(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: Annotated[PlainText, StringConstraints(min_length=3, max_length=500)]


class OnboardingAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["submit_for_review", "request_clarification", "approve"]
    reason: Annotated[PlainText, StringConstraints(min_length=3, max_length=500)] | None = None


class AssignIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    owner_id: int
