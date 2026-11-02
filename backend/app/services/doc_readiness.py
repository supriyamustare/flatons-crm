"""Whether a project has everything its welcome letters and payment demands need.

Document generation (Sprints 12-13) calls `require_ready` and refuses with the list of what's missing."""

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project import Project
from app.models.project_legal import ProjectBank, ProjectLegal
from app.services.cost_sheet import merged

LEGAL_FIELDS = {
    "developer_legal_name": "Developer's legal name",
    "rera_number": "RERA registration number",
    "registered_address": "Registered address",
    "signatory_name": "Signatory name",
    "signatory_designation": "Signatory designation",
    "gstin": "GSTIN",
}
BANK_FIELDS = {
    "bank_name": "Bank name",
    "account_holder_name": "Account holder name",
    "account_number_enc": "Account number",
    "ifsc": "IFSC code",
    "branch": "Branch",
}


class Readiness(BaseModel):
    ready: bool
    missing: list[str]  # plain-English names of what's missing
    legal_missing: list[str]
    bank_missing: list[str]
    schedule_ok: bool
    schedule_note: str


class NotReady(ValueError):
    def __init__(self, r: Readiness):
        super().__init__(f"Complete the project's details first: {', '.join(r.missing)}")
        self.readiness = r


async def check(db: AsyncSession, project: Project) -> Readiness:
    legal = await db.get(ProjectLegal, project.id)
    bank = await db.get(ProjectBank, project.id)
    legal_missing = [
        label for f, label in LEGAL_FIELDS.items() if not (legal and getattr(legal, f))
    ]
    bank_missing = [label for f, label in BANK_FIELDS.items() if not (bank and getattr(bank, f))]
    stages = merged(project.cost_sheet, None)["stages"] if project.cost_sheet else []
    total = round(sum(float(s["pct"]) for s in stages), 4)
    schedule_ok = bool(project.cost_sheet) and total == 100
    note = (
        f"{len(stages)} payment stages, 100%"
        if schedule_ok
        else "Set the payment stages in Cost sheet settings"
        if not project.cost_sheet
        else f"Payment stages add up to {total:g}%, not 100%"
    )
    missing = legal_missing + bank_missing + ([] if schedule_ok else ["Payment schedule"])
    return Readiness(
        ready=not missing,
        missing=missing,
        legal_missing=legal_missing,
        bank_missing=bank_missing,
        schedule_ok=schedule_ok,
        schedule_note=note,
    )


async def require_ready(db: AsyncSession, project: Project) -> None:
    r = await check(db, project)
    if not r.ready:
        raise NotReady(r)
