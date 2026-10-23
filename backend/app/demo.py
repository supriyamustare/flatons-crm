"""Realistic demo data for training, testing and the Phase 1 dashboard check.

Everything created is marked so it can be removed exactly:
  users     email ends with @demo.example.com
  projects  name starts with "Demo: "
  leads     sub_source = "DEMO DATA" (their activities, follow-ups, calls and visits go with them)
"""

import random
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.models.call import CONNECTED_OUTCOMES, CallDirection, CallLog, CallOutcome
from app.models.lead import (
    BuyingTimeline,
    Configuration,
    Lead,
    LeadActivity,
    LeadSource,
    LeadStatus,
)
from app.models.project import Project
from app.models.task import FollowUpTask, TaskStatus, TaskType
from app.models.user import Role, User
from app.models.visit import InterestLevel, SiteVisit, VisitSource, VisitStatus
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
    projects = [
        Project(name=f"{PROJECT_PREFIX}Green Meadows"),
        Project(name=f"{PROJECT_PREFIX}Skyline Towers"),
    ]
    db.add_all(projects)
    await db.flush()
    sellers = [*execs, *execs, manager]  # executives carry most leads

    counts = {"users": 4, "projects": 2, "leads": 0, "follow_ups": 0, "calls": 0, "visits": 0}
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
            source=rnd.choice(list(LeadSource)),
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
        )
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
    removed["projects"] = (
        await db.execute(delete(Project).where(Project.name.like(f"{PROJECT_PREFIX}%")))
    ).rowcount
    removed["users"] = (
        await db.execute(delete(User).where(User.email.like(f"%{DEMO_DOMAIN}")))
    ).rowcount
    return removed
