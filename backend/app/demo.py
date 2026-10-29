"""Realistic demo data for training, testing and the Phase 1 dashboard check.

Everything created is marked so it can be removed exactly:
  users     email ends with @demo.example.com
  projects  name starts with "Demo: " (as does the demo developer); buildings and units go with them
  leads     sub_source = "DEMO DATA" (their activities, follow-ups, calls and visits go with them)
"""

import random
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.models.call import CONNECTED_OUTCOMES, CallDirection, CallLog, CallOutcome
from app.models.channel_partner import ChannelPartner
from app.models.inventory import Building, Unit, UnitStatus, UnitType
from app.models.lead import (
    ACTIVE_SOURCES,
    BuyingTimeline,
    Configuration,
    Lead,
    LeadActivity,
    LeadSource,
    LeadStatus,
)
from app.models.marketing import Campaign, Channel, Expense, ExpenseCategory
from app.models.project import Developer, Project, ProjectStatus
from app.models.task import FollowUpTask, TaskStatus, TaskType
from app.models.user import Role, User
from app.models.visit import InterestLevel, SiteVisit, VisitSource, VisitStatus
from app.schemas.inventory import GenerateUnits
from app.services.inventory import generate_units
from app.services.leads import next_lead_code

DEMO_DOMAIN = "@demo.example.com"
DEMO_TAG = "DEMO DATA"
PROJECT_PREFIX = "Demo: "

FIRST = [
    "Anita",
    "Rahul",
    "Priya",
    "Vikram",
    "Sneha",
    "Arjun",
    "Kavya",
    "Rohan",
    "Meena",
    "Sanjay",
    "Pooja",
    "Amit",
    "Divya",
    "Nikhil",
    "Asha",
    "Kiran",
    "Neha",
    "Suresh",
    "Lata",
    "Manoj",
]
LAST = [
    "Desai",
    "Patil",
    "Sharma",
    "Joshi",
    "Kulkarni",
    "Iyer",
    "Shah",
    "Reddy",
    "Nair",
    "Gupta",
    "Mehta",
    "Rao",
    "Pawar",
    "Bhat",
    "Kapoor",
]
CITIES = ["Baner", "Wakad", "Hinjewadi", "Kharadi", "Viman Nagar", "Aundh", "Hadapsar", "Kothrud"]

# Rough real-world funnel: most leads are early, few are far along.
STATUS_WEIGHTS = {
    LeadStatus.new: 14,
    LeadStatus.not_reachable: 6,
    LeadStatus.contacted: 10,
    LeadStatus.qualified: 6,
    LeadStatus.follow_up: 10,
    LeadStatus.visit_scheduled: 6,
    LeadStatus.visit_done: 5,
    LeadStatus.revisit: 2,
    LeadStatus.negotiation: 3,
    LeadStatus.on_hold: 2,
    LeadStatus.booked: 2,
    LeadStatus.lost: 5,
    LeadStatus.junk: 2,
}


class DemoDataError(RuntimeError):
    pass


async def demo_present(db: AsyncSession) -> bool:
    return bool(
        await db.scalar(select(func.count()).select_from(Lead).where(Lead.sub_source == DEMO_TAG))
        or await db.scalar(
            select(func.count()).select_from(User).where(User.email.like(f"%{DEMO_DOMAIN}"))
        )
    )


async def seed_demo(
    db: AsyncSession, *, password: str, leads: int = 60, now: datetime | None = None, seed: int = 7
) -> dict[str, int]:
    """Create demo users, projects, leads, follow-ups, calls and visits. Refuses to run twice."""
    if await demo_present(db):
        raise DemoDataError("Demo data is already there. Run remove-demo first to start fresh.")
    rnd = random.Random(seed)
    now = now or datetime.now(UTC)
    hashed = hash_password(password)

    def person(name: str, role: Role) -> User:
        email = name.lower().replace(" ", ".") + DEMO_DOMAIN
        return User(email=email, full_name=name, role=role, hashed_password=hashed)

    manager = person("Meera Shah", Role.manager)
    execs = [person("Ravi Kumar", Role.executive), person("Kiran Rao", Role.executive)]
    docs = person("Farah Khan", Role.docs)
    db.add_all([manager, *execs, docs])
    developer = Developer(name=f"{PROJECT_PREFIX}Skyline Developers")
    db.add(developer)
    await db.flush()
    projects = [
        Project(
            name=f"{PROJECT_PREFIX}Green Meadows",
            developer_id=developer.id,
            status=ProjectStatus.under_construction,
            location="Baner, Pune",
            commission_pct=2,
        ),
        Project(
            name=f"{PROJECT_PREFIX}Skyline Towers",
            developer_id=developer.id,
            status=ProjectStatus.ready_to_move,
            location="Wakad, Pune",
            commission_pct=1.5,
        ),
    ]
    db.add_all(projects)
    await db.flush()
    # Buildings and a grid of units, with a realistic mix of statuses
    unit_count = 0
    for project, wings in ((projects[0], ("A Wing", "B Wing")), (projects[1], ("Tower 1",))):
        for order, wing in enumerate(wings):
            building = Building(project_id=project.id, name=wing, sort_order=order)
            db.add(building)
            await db.flush()
            unit_count += await generate_units(
                db,
                building,
                GenerateUnits(
                    floor_from=1,
                    floor_to=8 if project is projects[0] else 12,
                    units_per_floor=4,
                    unit_type=UnitType.bhk2,
                    carpet_sqft=680,
                    builtup_sqft=890,
                    base_price=7_200_000,
                ),
            )
    await db.flush()
    for unit in await db.scalars(
        select(Unit).join(Project).where(Project.name.like(f"{PROJECT_PREFIX}%"))
    ):
        roll = rnd.random()
        if roll < 0.18:
            unit.status = UnitStatus.sold
        elif roll < 0.22:
            unit.status = UnitStatus.withdrawn
        if unit.unit_no.endswith(("01", "04")):
            unit.unit_type = UnitType.bhk3
            unit.carpet_sqft, unit.builtup_sqft, unit.base_price = 980, 1250, 10_500_000
            unit.current_asking_price = unit.base_price
    sellers = [*execs, *execs, manager]  # executives carry most leads

    # Marketing: campaigns with spend over the last ~6 weeks. The expo has spend but no leads
    # yet, so reports show its cost per lead as N/A.
    campaign_specs = [
        (
            "Google Ads: Green Meadows",
            Channel.google_ads,
            projects[0],
            [(4, 38_000), (11, 42_000), (18, 40_000), (25, 45_000), (32, 39_000)],
        ),
        ("99acres premium listing", Channel.portal_99acres, None, [(2, 60_000), (30, 60_000)]),
        ("Diwali hoardings", Channel.print, projects[1], [(9, 1_25_000), (14, 35_000)]),
        ("Property expo stall", Channel.event, None, [(1, 85_000)]),
    ]
    campaigns: dict[str, Campaign] = {}
    for name, channel, proj, spends in campaign_specs:
        camp = Campaign(
            name=f"{PROJECT_PREFIX}{name}",
            channel=channel,
            project_id=proj.id if proj else None,
            start_date=(now - timedelta(days=45)).date(),
            created_by_id=manager.id,
        )
        db.add(camp)
        await db.flush()
        campaigns[channel.value] = camp
        for days_ago, amount in spends:
            db.add(
                Expense(
                    campaign_id=camp.id,
                    spent_on=(now - timedelta(days=days_ago)).date(),
                    amount=amount,
                    category=ExpenseCategory.ad_spend
                    if channel != Channel.print
                    else ExpenseCategory.printing,
                    vendor="Demo vendor",
                    entered_by_id=manager.id,
                )
            )
    source_to_campaign = {
        LeadSource.google_ads: campaigns["google_ads"],
        LeadSource.acres_99: campaigns["99acres"],
        LeadSource.print: campaigns["print"],
    }

    counts = {
        "users": 4,
        "projects": 2,
        "units": 0,
        "leads": 0,
        "follow_ups": 0,
        "calls": 0,
        "visits": 0,
    }
    counts["campaigns"] = len(campaigns)
    # Channel partners (marked "Demo partner"), linked to leads that came through a partner
    partners = []
    for i, (name, company) in enumerate(
        [
            ("Amit Shah", "Square Realty"),
            ("Neha Joshi", "Prime Homes Advisory"),
            ("Rohit Kulkarni", "Pune Property Hub"),
        ]
    ):
        cp = ChannelPartner(
            name=f"Demo partner: {name}",
            company_name=company,
            mobile=f"+9170000000{i:02d}",
            email=f"partner{i}{DEMO_DOMAIN}",
            rera_number=f"A5210000{i:04d}",
            created_by_id=manager.id,
        )
        db.add(cp)
        partners.append(cp)
    await db.flush()
    counts["channel_partners"] = len(partners)
    counts["units"] = unit_count
    statuses = list(STATUS_WEIGHTS)
    weights = list(STATUS_WEIGHTS.values())

    for _ in range(leads):
        created = now - timedelta(days=rnd.uniform(0, 45), hours=rnd.uniform(0, 8))
        owner = rnd.choice(sellers) if rnd.random() > 0.08 else None
        status = rnd.choices(statuses, weights)[0]
        project = rnd.choice(projects)
        budget = rnd.choice([45, 55, 65, 80, 95, 120]) * 100_000
        lead = Lead(
            lead_code=await next_lead_code(db, created),
            name=f"{rnd.choice(FIRST)} {rnd.choice(LAST)}",
            mobile=f"+919{rnd.randint(100000000, 999999999)}",
            city=rnd.choice(CITIES),
            source=rnd.choice(ACTIVE_SOURCES),
            sub_source=DEMO_TAG,
            project_id=project.id if rnd.random() > 0.2 else None,
            configuration=rnd.choice(
                [Configuration.bhk1, Configuration.bhk2, Configuration.bhk2, Configuration.bhk3]
            ),
            budget_min=budget,
            budget_max=budget + 1_500_000,
            timeline=rnd.choice(list(BuyingTimeline)),
            estimated_value=budget + 1_000_000,
            status=status,
            lost_reason="Bought elsewhere"
            if status == LeadStatus.lost
            else ("Wrong number" if status == LeadStatus.junk else None),
            assigned_to_id=owner.id if owner else None,
            created_by_id=(owner or manager).id,
            created_at=created,
            last_activity_at=created,
            # Entered its current stage somewhere between creation and now
            status_changed_at=created + (now - created) * rnd.uniform(0.2, 1.0),
        )
        camp = source_to_campaign.get(lead.source)
        if camp is None and lead.source == LeadSource.social and rnd.random() < 0.5:
            camp = campaigns["google_ads"]
        lead.campaign_id = camp.id if camp else None
        if lead.source == LeadSource.channel_partner:
            lead.channel_partner_id = rnd.choice(partners).id
        db.add(lead)
        await db.flush()
        db.add(
            LeadActivity(
                lead_id=lead.id,
                actor_id=(owner or manager).id,
                type="created",
                details={"source": lead.source.value},
                created_at=created,
            )
        )
        counts["leads"] += 1
        if owner is None:
            continue

        # Calls: 0-4 per lead, after it was created
        for _ in range(rnd.choice([0, 1, 1, 2, 2, 3, 4])):
            at = created + (now - created) * rnd.random()
            outcome = rnd.choice(list(CallOutcome))
            db.add(
                CallLog(
                    lead_id=lead.id,
                    user_id=owner.id,
                    direction=rnd.choice([CallDirection.outgoing] * 4 + [CallDirection.incoming]),
                    outcome=outcome,
                    called_at=at,
                    duration_sec=rnd.randint(40, 600) if outcome in CONNECTED_OUTCOMES else None,
                )
            )
            db.add(
                LeadActivity(
                    lead_id=lead.id,
                    actor_id=owner.id,
                    type="call_logged",
                    created_at=at,
                    details={
                        "outcome": outcome.value,
                        "direction": "outgoing",
                        "connected": outcome in CONNECTED_OUTCOMES,
                    },
                )
            )
            counts["calls"] += 1
            lead.last_activity_at = max(lead.last_activity_at, at)

        # Most leads were touched in the last week; the rest go quiet ("stale" on the pipeline)
        if rnd.random() < 0.65:
            touched = max(created, now - timedelta(days=rnd.uniform(0, 6)))
            db.add(
                LeadActivity(
                    lead_id=lead.id,
                    actor_id=owner.id,
                    type="note",
                    created_at=touched,
                    note="Followed up on WhatsApp",
                )
            )
            lead.last_activity_at = max(lead.last_activity_at, touched)

        # Follow-ups: open ones spread across overdue / today / upcoming, plus some done
        if status not in {LeadStatus.lost, LeadStatus.junk, LeadStatus.booked}:
            when = rnd.choice([-3, -1, -0.1, 0.1, 0.2, 1, 2, 5])  # days from now
            task_status = TaskStatus.completed if rnd.random() < 0.25 else TaskStatus.pending
            due = now + timedelta(days=when)
            db.add(
                FollowUpTask(
                    lead_id=lead.id,
                    assigned_to_id=owner.id,
                    created_by_id=owner.id,
                    task_type=rnd.choice(
                        [TaskType.call, TaskType.call, TaskType.whatsapp, TaskType.meeting]
                    ),
                    due_at=due,
                    status=task_status,
                    completed_at=due if task_status == TaskStatus.completed else None,
                    completed_by_id=owner.id if task_status == TaskStatus.completed else None,
                    completion_note="Spoke to customer"
                    if task_status == TaskStatus.completed
                    else None,
                )
            )
            counts["follow_ups"] += 1

        # Visits for leads that got that far
        if status in {
            LeadStatus.visit_scheduled,
            LeadStatus.visit_done,
            LeadStatus.revisit,
            LeadStatus.negotiation,
            LeadStatus.booked,
        }:
            done = status != LeadStatus.visit_scheduled
            at = (
                now - timedelta(days=rnd.uniform(1, 20))
                if done
                else now + timedelta(days=rnd.uniform(-0.5, 6))
            )
            visit = SiteVisit(
                lead_id=lead.id,
                project_id=project.id,
                host_id=owner.id,
                created_by_id=owner.id,
                visit_source=rnd.choice(list(VisitSource)),
                scheduled_at=at,
                status=VisitStatus.completed if done else VisitStatus.scheduled,
            )
            if done:
                visit.feedback = "Liked the sample flat"
                visit.interest_level = rnd.choice(list(InterestLevel))
                visit.closed_at = at
                visit.closed_by_id = owner.id
            db.add(visit)
            counts["visits"] += 1
        if rnd.random() < 0.08:
            db.add(
                SiteVisit(
                    lead_id=lead.id,
                    project_id=project.id,
                    host_id=owner.id,
                    created_by_id=owner.id,
                    visit_source=VisitSource.sales_follow_up,
                    status=rnd.choice([VisitStatus.no_show, VisitStatus.cancelled]),
                    scheduled_at=now - timedelta(days=rnd.uniform(1, 10)),
                    cancellation_reason="Customer travelling",
                )
            )
            counts["visits"] += 1

    return counts


async def remove_demo(db: AsyncSession) -> dict[str, int]:
    """Delete everything seed_demo created, and nothing else."""
    lead_ids = select(Lead.id).where(Lead.sub_source == DEMO_TAG)
    removed = {
        "visits": (
            await db.execute(delete(SiteVisit).where(SiteVisit.lead_id.in_(lead_ids)))
        ).rowcount,
        "calls": (await db.execute(delete(CallLog).where(CallLog.lead_id.in_(lead_ids)))).rowcount,
        "follow_ups": (
            await db.execute(delete(FollowUpTask).where(FollowUpTask.lead_id.in_(lead_ids)))
        ).rowcount,
    }
    await db.execute(delete(LeadActivity).where(LeadActivity.lead_id.in_(lead_ids)))
    removed["leads"] = (await db.execute(delete(Lead).where(Lead.sub_source == DEMO_TAG))).rowcount
    removed["channel_partners"] = (
        await db.execute(delete(ChannelPartner).where(ChannelPartner.name.like("Demo partner:%")))
    ).rowcount
    demo_campaigns = select(Campaign.id).where(Campaign.name.like(f"{PROJECT_PREFIX}%"))
    await db.execute(delete(Expense).where(Expense.campaign_id.in_(demo_campaigns)))
    removed["campaigns"] = (
        await db.execute(delete(Campaign).where(Campaign.name.like(f"{PROJECT_PREFIX}%")))
    ).rowcount
    removed["projects"] = (
        await db.execute(delete(Project).where(Project.name.like(f"{PROJECT_PREFIX}%")))
    ).rowcount
    # The demo developer can only go once its projects are gone (projects -> developer is RESTRICT)
    await db.execute(delete(Developer).where(Developer.name.like(f"{PROJECT_PREFIX}%")))
    removed["users"] = (
        await db.execute(delete(User).where(User.email.like(f"%{DEMO_DOMAIN}")))
    ).rowcount
    return removed
