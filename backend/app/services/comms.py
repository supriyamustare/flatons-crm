"""The notification engine. Modules call emit(event, case, context, ref); approved templates decide what is sent, on which
channel, to whom and when. Consent and opt-outs come from the customer profile. Messages carry no links to confidential
documents (templates are checked): customers are pointed to the portal instead.

Delivery: dispatch() runs every 2 minutes. Email goes through the SMTP settings; SMS and WhatsApp wait for providers.
A message for a channel that isn't set up is HELD (not lost) and goes out once it is. Failures retry 3 times (5 min,
30 min, 2 h), then stop with the reason.
"""

import asyncio
import re
import smtplib
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.config import get_settings
from app.models.comms import CommMessage, CommTemplate
from app.models.postsales import CustomerProfile, PostSalesCase

BASE = ["customer", "project", "unit", "case_code", "company"]
EVENTS: dict[str, dict] = {
    "onboarding_pending": {
        "label": "Onboarding pending (KYC and details needed)",
        "fields": [],
        "channels": ["email", "sms"],
        "subject": "Welcome to {project}: next steps for unit {unit}",
        "email": "Dear {customer},\n\nThank you for booking unit {unit} at {project}. Our customer relations team will help you complete your onboarding: we need your KYC documents and contact details.\n\nYour reference: {case_code}.\n\nRegards,\n{company}",
        "sms": "Dear {customer}, welcome to {project} (unit {unit}). Our team will contact you to complete KYC. Ref {case_code}. -{company}",
    },
    "kyc_clarification": {
        "label": "KYC clarification required",
        "fields": ["document", "reason"],
        "channels": ["email"],
        "subject": "{project} unit {unit}: we need a clarification on your {document}",
        "email": "Dear {customer},\n\nWe could not accept your {document}: {reason}\n\nPlease share a corrected copy with your relationship executive.\n\nRef {case_code}.\n{company}",
    },
    "agreement_draft_ready": {
        "label": "Agreement draft ready for review",
        "fields": ["agreement_no"],
        "channels": ["email"],
        "subject": "{project} unit {unit}: your agreement draft is ready",
        "email": "Dear {customer},\n\nThe draft agreement {agreement_no} for unit {unit} is ready for your review. Your relationship executive will share it with you securely.\n\nRef {case_code}.\n{company}",
    },
    "agreement_registered": {
        "label": "Agreement registered",
        "fields": ["registration_no", "registered_on"],
        "channels": ["email"],
        "subject": "{project} unit {unit}: agreement registered",
        "email": "Dear {customer},\n\nYour agreement for unit {unit} was registered on {registered_on} (registration no. {registration_no}).\n\nRef {case_code}.\n{company}",
    },
    "demand_issued": {
        "label": "Demand issued",
        "fields": ["stage", "amount", "due_date"],
        "channels": ["email", "sms"],
        "mandatory": True,
        "subject": "{project} unit {unit}: payment demand for {stage}",
        "email": "Dear {customer},\n\nA payment of Rs {amount} for the {stage} stage of unit {unit} is due by {due_date}. Your demand letter will be shared with you securely by your relationship executive.\n\nRef {case_code}.\n{company}",
        "sms": "Dear {customer}, payment of Rs {amount} for {stage} (unit {unit}, {project}) is due by {due_date}. Ref {case_code}. -{company}",
    },
    "payment_due_soon": {
        "label": "Payment approaching its due date",
        "fields": ["stage", "amount", "due_date"],
        "channels": ["email", "sms"],
        "subject": "Reminder: payment for {stage} due on {due_date}",
        "email": "Dear {customer},\n\nA reminder that Rs {amount} for the {stage} stage of unit {unit} is due on {due_date}. Please ignore this if you have already paid.\n\nRef {case_code}.\n{company}",
        "sms": "Reminder: Rs {amount} for {stage} (unit {unit}) due on {due_date}. Ignore if paid. Ref {case_code}. -{company}",
    },
    "payment_received": {
        "label": "Payment received (receipt issued)",
        "fields": ["amount", "receipt_no", "received_on"],
        "channels": ["email"],
        "subject": "{project} unit {unit}: payment received, receipt {receipt_no}",
        "email": "Dear {customer},\n\nWe have received Rs {amount} on {received_on} towards unit {unit}. Receipt {receipt_no} has been issued.\n\nRef {case_code}.\n{company}",
    },
    "document_released": {
        "label": "New document available",
        "fields": ["document"],
        "channels": ["email"],
        "subject": "{project} unit {unit}: a new document is available",
        "email": "Dear {customer},\n\nA new document, {document}, has been added to your file. Your relationship executive will share it with you securely.\n\nRef {case_code}.\n{company}",
    },
    "complaint_created": {
        "label": "Complaint or request registered",
        "fields": ["ticket_no", "title"],
        "channels": ["email"],
        "subject": "Your request {ticket_no} has been registered",
        "email": "Dear {customer},\n\nWe have registered your request {ticket_no}: {title}. We will keep you updated.\n\nRef {case_code}.\n{company}",
    },
    "possession_appointment": {
        "label": "Possession appointment confirmed",
        "fields": ["when", "location"],
        "channels": ["email", "sms"],
        "subject": "{project} unit {unit}: possession appointment confirmed",
        "email": "Dear {customer},\n\nYour possession appointment for unit {unit} is confirmed for {when} at {location}. Please bring your identity proof.\n\nRef {case_code}.\n{company}",
        "sms": "Possession of unit {unit} ({project}) confirmed for {when} at {location}. Bring ID proof. Ref {case_code}. -{company}",
    },
    "defect_rectified": {
        "label": "Defect rectified (please confirm)",
        "fields": ["defect_no", "description"],
        "channels": ["email"],
        "subject": "{defect_no}: the repair is complete",
        "email": "Dear {customer},\n\nThe repair for {defect_no} ({description}) is complete and has passed our quality check. Please let us know if you are satisfied.\n\nRef {case_code}.\n{company}",
    },
    "refund_processed": {
        "label": "Refund processed",
        "fields": ["amount", "paid_on", "utr"],
        "channels": ["email"],
        "subject": "{project} unit {unit}: refund processed",
        "email": "Dear {customer},\n\nYour refund of Rs {amount} was paid on {paid_on} (reference {utr}).\n\nRef {case_code}.\n{company}",
    },
}
LINK = re.compile(r"https?://|www\.|/api/", re.I)
FIELD = re.compile(r"{([a-z_]+)}")
RETRY_MINUTES = (5, 30, 120)


def now() -> datetime:
    return datetime.now(UTC)


def check_template(event: str, subject: str | None, body: str) -> str | None:
    """None when fine, else the problem: no links (confidential documents go through the portal), only known fields."""
    if event not in EVENTS:
        return "Unknown event"
    text = f"{subject or ''}\n{body}"
    if LINK.search(text):
        return "Templates can't contain links: documents are shared through the customer portal, never as open links"
    allowed = set(BASE) | set(EVENTS[event]["fields"])
    unknown = sorted(set(FIELD.findall(text)) - allowed)
    if unknown:
        return f"Unknown fields: {', '.join('{' + u + '}' for u in unknown)}. Available: {', '.join('{' + a + '}' for a in sorted(allowed))}"
    return None


class _Safe(dict):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def render(t: CommTemplate | dict, ctx: dict) -> tuple[str | None, str]:
    subj, body = (
        (t.subject, t.body) if isinstance(t, CommTemplate) else (t.get("subject"), t["body"])
    )
    c = _Safe({k: ("" if v is None else v) for k, v in ctx.items()})
    return (subj.format_map(c) if subj else None), body.format_map(c)


def money(n) -> str:
    s = str(int(n))
    head, tail = s[:-3], s[-3:]
    parts = []
    while len(head) > 2:
        parts.insert(0, head[-2:])
        head = head[:-2]
    if head:
        parts.insert(0, head)
    return ",".join([*parts, tail]) if parts else tail


async def emit(db, event: str, case: PostSalesCase, ctx: dict, ref: str | int) -> list[CommMessage]:
    """Queue the customer messages for an event. Safe to call twice for the same ref: duplicates are ignored."""
    project_id = case.booking.project_id
    tpls = list(
        await db.scalars(
            select(CommTemplate).where(
                CommTemplate.event == event, CommTemplate.status == "approved"
            )
        )
    )
    chosen: dict[str, CommTemplate] = {}
    for t in sorted(
        tpls, key=lambda x: x.project_id is not None
    ):  # a project's own template overrides the general one
        if t.project_id in (None, project_id):
            chosen[t.channel] = t
    if not chosen:
        return []
    profile = await db.scalar(select(CustomerProfile).where(CustomerProfile.case_id == case.id))
    b = case.booking
    from app.models.project_legal import ProjectLegal

    legal = await db.scalar(select(ProjectLegal).where(ProjectLegal.project_id == project_id))
    name = (
        (profile.legal_name if profile and profile.legal_name else None)
        or b.customer_name
        or b.lead.name
    )
    full = {
        "customer": name,
        "project": b.project.name,
        "unit": b.unit.unit_no,
        "case_code": f"PSC-{case.id:05d}",
        "company": (
            legal.developer_legal_name if legal and legal.developer_legal_name else "Flatons"
        ),
        **{k: (money(v) if k == "amount" and isinstance(v, int) else v) for k, v in ctx.items()},
    }
    out = []
    for ch, t in chosen.items():
        status, reason = "queued", None
        recipient = (profile.email if ch == "email" else profile.mobile) if profile else None
        if profile is None or profile.consent_electronic_at is None:
            status, reason = (
                "skipped",
                "No consent to electronic communication on file: send by letter",
            )
        elif not recipient:
            status, reason = (
                "skipped",
                f"No {'email address' if ch == 'email' else 'mobile number'} on file",
            )
        elif ch == "whatsapp" and not profile.contact_whatsapp:
            status, reason = "skipped", "The customer hasn't opted in to WhatsApp"
        elif not t.mandatory and not getattr(profile, f"contact_{ch}", True):
            status, reason = "skipped", f"The customer opted out of {ch}"
        subj, body = render(t, full)
        m = CommMessage(
            case_id=case.id,
            event=event,
            template_id=t.id,
            template_version=t.version,
            channel=ch,
            recipient=recipient,
            recipient_name=name,
            subject=subj,
            body=body,
            status=status,
            reason=reason,
            send_after=now() + timedelta(minutes=t.delay_minutes),
            dedupe_key=f"{event}:{ref}:{ch}:{t.id}"[:200],
        )
        try:
            async with db.begin_nested():
                db.add(m)
                await db.flush()
            out.append(m)
        except IntegrityError:
            pass  # already queued for this event and reference
    return out


def channel_ready(channel: str) -> str | None:
    """None when the channel can send, else why it can't yet."""
    s = get_settings()
    if channel == "email":
        return (
            None
            if s.smtp_host and s.smtp_from
            else "Email isn't set up yet (SMTP settings on the server)"
        )
    return f"{channel.upper() if channel == 'sms' else 'WhatsApp'} provider isn't chosen yet"


def _send_email(to: str, subject: str, body: str) -> None:
    s = get_settings()
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = s.smtp_from, to, subject or "(no subject)"
    msg.set_content(body)
    with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=20) as smtp:
        if s.smtp_tls:
            smtp.starttls()
        if s.smtp_user:
            smtp.login(s.smtp_user, s.smtp_pass)
        smtp.send_message(msg)


SENDERS = {"email": _send_email}


async def dispatch(db, at: datetime | None = None, senders: dict | None = None) -> dict:
    """Send what's due. Held messages go out once their channel is set up; failures retry, then stop with the reason."""
    at = at or now()
    senders = senders or SENDERS
    counts = {"sent": 0, "failed": 0, "held": 0, "retry": 0}
    due = list(
        await db.scalars(
            select(CommMessage)
            .where(CommMessage.status.in_(["queued", "held"]), CommMessage.send_after <= at)
            .order_by(CommMessage.id)
            .limit(200)
        )
    )
    for m in due:
        blocked = (
            channel_ready(m.channel) if m.channel not in senders or senders is SENDERS else None
        )
        if blocked:
            if m.status != "held":
                counts["held"] += 1
            m.status, m.reason = "held", blocked
            continue
        try:
            await asyncio.to_thread(senders[m.channel], m.recipient, m.subject, m.body)
            m.status, m.sent_at, m.reason = "sent", at, None
            m.attempts += 1
            counts["sent"] += 1
        except Exception as exc:  # noqa: BLE001 - any delivery failure is recorded and retried
            m.attempts += 1
            m.reason = f"{type(exc).__name__}: {exc}"[:500]
            if m.attempts >= len(RETRY_MINUTES) + 1:
                m.status = "failed"
                counts["failed"] += 1
            else:
                m.status, m.send_after = (
                    "queued",
                    at + timedelta(minutes=RETRY_MINUTES[m.attempts - 1]),
                )
                counts["retry"] += 1
    return counts
