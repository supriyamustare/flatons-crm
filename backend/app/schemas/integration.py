from datetime import datetime
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, StringConstraints, model_validator

from app.models.integration import InboundStatus, IntegrationKind
from app.schemas.common import PlainText
from app.schemas.lead import CampaignBrief
from app.schemas.project import ProjectBrief

Secret = Annotated[str, StringConstraints(strip_whitespace=True, min_length=10, max_length=500)]


class IntegrationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    kind: IntegrationKind
    is_active: bool
    default_campaign_id: int | None
    default_project_id: int | None
    received_count: int
    last_received_at: datetime | None
    facebook_ready: bool = False
    path: str = ""  # where the platform sends enquiries, e.g. /api/inbound/3
    created_at: datetime


class IntegrationCreated(BaseModel):
    integration: IntegrationOut
    secret: str  # shown once


class IntegrationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Annotated[PlainText, StringConstraints(max_length=100)]
    kind: IntegrationKind
    default_campaign_id: int | None = None
    default_project_id: int | None = None
    fb_app_secret: Secret | None = None
    fb_page_token: Secret | None = None

    @model_validator(mode="after")
    def _facebook_needs_secrets(self) -> "IntegrationCreate":
        if self.kind == IntegrationKind.website:
            raise ValueError("Website connections are no longer used")
        if self.kind == IntegrationKind.facebook and not (
            self.fb_app_secret and self.fb_page_token
        ):
            raise ValueError("Facebook needs the app secret and a page access token")
        return self


class IntegrationUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Annotated[PlainText, StringConstraints(max_length=100)] | None = None
    is_active: bool | None = None
    default_campaign_id: int | None = None
    default_project_id: int | None = None
    fb_app_secret: Secret | None = None
    fb_page_token: Secret | None = None


class InboundEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    received_at: datetime
    external_id: str | None
    status: InboundStatus
    lead_id: int | None
    error: str | None
    payload: dict[str, Any]


class InboxItem(BaseModel):
    id: int
    lead_code: str
    name: str
    mobile: str
    source: str
    sub_source: str | None
    project: ProjectBrief | None
    campaign: CampaignBrief | None
    message: str | None
    created_at: datetime


class Inbox(BaseModel):
    count: int
    items: list[InboxItem]
