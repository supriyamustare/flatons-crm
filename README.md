# Flatons CRM

Lead management, inventory, bookings and post-sales document engine for Flatons.

- **Backend:** Python 3.12, FastAPI, SQLAlchemy (async) + Alembic, PostgreSQL 16, Celery + Redis
- **Frontend:** React 19, TypeScript, Vite, Tailwind CSS v4, React Router, TanStack Query
- **Server:** Ubuntu on Google Cloud, Nginx, Gunicorn, systemd

## Repository layout

```
backend/     FastAPI app (app/api, core, models, schemas, services, tasks), tests, migrations
frontend/    React app (src/components, pages, hooks, lib)
nginx/       Nginx site config
systemd/     flatons-api, flatons-worker, flatons-beat service files
scripts/     deploy.sh (and backup.sh from Sprint 17)
docker-compose.dev.yml   PostgreSQL + Redis for local development only
```

## Branches

- `main` — production; changes only via pull request
- `dev` — integration branch
- `feature/<name>` — work branches, merged into `dev` by pull request

## Local development

Requirements: Python 3.12, [Poetry](https://python-poetry.org/) 2.x, Node 24 LTS, Docker Desktop.

```bash
# 1. Database + Redis
docker compose -f docker-compose.dev.yml up -d

# 2. Backend (http://localhost:8000/api/docs)
cd backend
cp .env.example .env          # use the "Local Docker dev" DATABASE_URL and set a SECRET_KEY
poetry install
poetry run uvicorn app.main:app --reload

# 3. Frontend (http://localhost:5173) — in a second terminal
cd frontend
npm install
npm run dev
```

## Database migrations

Schema changes go through Alembic and are never applied by hand in production.

```bash
cd backend
poetry run alembic revision --autogenerate -m "describe the change"   # then review the file
poetry run alembic upgrade head
```

`scripts/deploy.sh` runs `alembic upgrade head` automatically on every deploy.

## First admin user

Users are created by an admin in the app, so the very first admin is created from the command line:

```bash
cd backend
poetry run python -m app.cli create-admin --email you@company.com --name "Your Name"
```

On the server, run it as the `crm` user:

```bash
sudo -iu crm bash -c 'cd ~/flatons-crm/backend && .venv/bin/python -m app.cli create-admin --email you@company.com --name "Your Name"'
```

## Tests and linting

Integration tests need the local PostgreSQL from `docker-compose.dev.yml`. They create and rebuild
a separate `flatons_crm_test` database, so your development data is never touched.

```bash
cd backend
poetry run pytest
poetry run ruff check . && poetry run ruff format --check .

cd ../frontend
npm run typecheck
npm test
```

## Leads (Sprint 2)

- Lead IDs look like `LEAD-20261022-0001`, numbered per day in India time.
- Executives see and work only the leads assigned to them; leads they create are assigned to them.
  Managers and admins see everything and can reassign. Documents staff have read-only access.
- Lost and Junk need a reason. Only managers and admins can set or undo Booked.
- Duplicate phone numbers or emails trigger a warning, never a block.
- Search and filters are sent in the body of `POST /api/leads/search`, so phone numbers and
  names never appear in URLs or server logs.

## Follow-ups and notifications (Sprint 3)

- Follow-ups belong to a lead and a person. Views: Today (everything due today, including
  anything already late), Overdue (past due and not done), Upcoming (after today) and Completed.
  "Overdue" is worked out from the due time, so it is always current.
- Completing needs a short note, which goes on the lead's timeline. Rescheduling closes the old
  follow-up and creates a new one linked to it, so the history of postponements is kept.
- Executives work their own follow-ups. Managers and admins see everyone's and can assign
  follow-ups to others. Documents staff don't use follow-ups.
- In-app notifications: lead assigned to you, follow-up given to you by someone else, and a daily
  digest at 08:00 India time (Celery beat job `followups.daily_digest`). The bell checks for new
  notifications every minute. Email delivery comes in Sprint 15.

## Calls and site visits (Sprint 4)

- Calls: outcome (connected: Interested, Call back later, Not interested; not connected: No answer,
  Busy, Switched off/unreachable, Wrong number), direction, optional duration and notes. Setting a
  next date creates a follow-up. Logged from a follow-up, a call can close that follow-up too.
  Calls can be logged up to 30 days after they happened, never in the future.
- Site visits: project, date and time, how the visit came about (separate from the lead source) and
  who hosts it. Afterwards: completed (feedback, interest, next step, optional follow-up), no-show,
  rescheduled or cancelled (reason required). Outcomes can be recorded from the visit day on.
- Lead status moves automatically: scheduling a visit moves an early-stage lead to Visit scheduled;
  completing one moves it to Visit done (Revisit for later visits). Leads in Negotiation, On hold,
  Booked, Lost or Junk are never changed automatically. These changes are marked "automatic" in the
  timeline and audit log.
- The 8:00 daily digest also counts the day's site visits.

## Dashboards (Sprint 5)

`GET /api/dashboard/admin` (admins, managers: whole team) and `GET /api/dashboard/executive`
(your own work). Periods: `today`, `7d`, `30d`, or `custom` with `date_from`/`date_to` (max one year),
all in India time. Exact definitions are on `Kpis` in `backend/app/schemas/dashboard.py`:

- total leads (any date) and new leads (created in the period); deleted leads never count
- follow-ups due today (incl. today's late ones) and overdue follow-ups (any day)
- site visits in the period, excluding cancelled; and those completed
- calls in the period, connected calls, and connection rate (N/A when there were no calls)

`tests/test_dashboard.py` checks every figure against plain SQL on a 60-lead dataset.

### Dashboard overview (everyone in sales; managers can pick a person)

`GET /api/dashboard/overview?person_id=&tab=`: summary line (deals in Negotiation, New leads with no call yet),
tiles (follow-ups due by end of today incl. overdue, visits today, in closing), this week (Mon–today) and this
month for completed site visits, **sales closed** and **sales value** (live bookings by booking date), performance
cards (enquiries, site visits, sales, and spend with cost per sale for the team or calls for one person) with the
change against the **same number of days last month** and a 30-day trend, lead tabs (Fresh, Due today, Visit
booked, Closing, Re-engage = quiet 7+ days) and This month (new, active, qualified or further, unassigned, active
rate, win rate). Executives always get their own figures. Definitions: `Overview` in `backend/app/schemas/overview.py`.
The header search (Ctrl/⌘+K) passes the query to Leads in navigation state, never the address bar.

### Dashboard insights

`GET /api/dashboard/insights?person_id=`: project inventory (units sold or booked / on hold / available, price
range of units still for sale, bookings this month), lead status split (being worked = activity in the last 7
days, gone quiet, unassigned, booked, lost/junk), New leads with no call yet by owner, median first response
this month, follow-ups and site visits scheduled in the next 30 days, 12 months of leads received and deals
closed (bookings, plus leads marked Booked without a booking record), source performance over 12 months, and
recent bookings. Definitions: `Insights` in `backend/app/schemas/insights.py`; `tests/test_insights.py` checks
them against SQL. Charts on the dashboard are plain SVG (no chart library), with hidden tables for screen readers.

### Bookings

`/api/bookings`: an executive (or manager) books a unit for a lead; the unit row is locked (`SELECT … FOR UPDATE`)
and partial unique indexes allow one live booking per unit and per lead. The unit turns Booked, the lead Booked,
managers and admins are notified. Managers/admins edit details, record commission received, and cancel (reason
required; the unit returns to Available and the lead to Negotiation). Expected commission = agreed price × the
project's commission %. Leads marked Booked without a booking are listed as `missing_details`. CSV export for
managers. The dashboard's commission revenue uses a booking's expected commission where one exists.
Screens: **Bookings** (totals, filters, "details missing", CSV for managers), each booking's page (customer,
flat, deal, commission, history; managers edit, record commission received, cancel), **Book a flat** on a
lead's page (only bookable flats are offered), and **View booking** on booked units in the building grid.

### Business figures (managers and admins, Team view)

- **Leads generated**: leads created in the period. **Leads booked**: leads that moved to Booked in the period.
- **Commission revenue (estimated)**: for each booked lead, deal value (estimated value, else top of budget,
  else bottom) × its project's **Flatons commission %** (set by admins on each project, 0–100).
- **Marketing expense**: expenses dated in the period. **Estimated profit** = revenue − expense (shown as a
  loss in red when negative).
- Booked leads that can't be valued (no project, no commission % on the project, or no value or budget) are
  left out of revenue and counted separately on screen. From Sprint 11, real booking prices replace the
  estimated deal value. Executives, and anyone's "Mine" view, never see these figures.

### Team performance (managers and admins, Team view)

One row per sales person (all executives, plus managers/admins with any activity), following the dashboard
period except **Calls today**, which is always today: calls and connected (%), completed site visits,
**converted** (their leads that moved to Booked in the period), **dead** (moved to Lost or Junk in the period),
**closing rate** = converted ÷ (converted + dead) (N/A when none closed), **open leads** (assigned now and still
in progress) and **overdue** follow-ups. Each name links to that person's Staff report. Definitions are on
`TeamMember` in `backend/app/schemas/dashboard.py`; `tests/test_dashboard.py` checks every figure against SQL.

## Demo data

Clearly marked data for training and testing (users `@demo.example.com`, projects "Demo: …",
leads tagged "DEMO DATA"). `remove-demo` deletes exactly that and nothing else.

```bash
poetry run python -m app.cli seed-demo        # asks for the demo users' password
poetry run python -m app.cli remove-demo
```

On a production server both commands refuse unless you add `--allow-production`.

## Installable app (PWA)

`frontend/public/manifest.webmanifest` plus icons make the CRM installable ("Add to Home Screen").
Android Chrome only offers installation over **HTTPS**; iPhone Safari works via Share → Add to Home
Screen. The icons are placeholders made from the "F" mark; replace the PNGs in `frontend/public/`
with the official logo at the same sizes. Offline support arrives in Sprint 16.

## Projects and inventory (Sprint 6)

- **Developer projects** (a builder's new project) must have a developer; **resale listings** must not.
  This is a database CHECK constraint, not just a form rule. Existing projects from before Sprint 6
  were attached to a placeholder developer, "Developer to be confirmed"; an admin should edit those
  projects and choose the real developer.
- Developer projects: Building → Floor → Unit. Admins generate floors and units in bulk (e.g. floors
  1–4 × 6 units → 101…406; ground floor G01, basements B1-01). Resale units belong to the project
  directly, with an optional "where" note.
- Unit status: Available, On hold, Booked (set by bookings in Sprint 11), Sold, Withdrawn. Admins set
  Available/Withdrawn/Sold by hand; holds and bookings have their own flows.
- **Holds** (admins and managers): up to 14 days, optionally for a lead. Every status change locks the
  unit row first (`SELECT … FOR UPDATE`), so two people can never hold or book the same unit at once;
  `tests/test_inventory.py::test_simultaneous_holds_only_one_wins` fires five requests at the same
  instant to prove it. Expired holds show as expired immediately and are released by the Celery beat job
  `inventory.release_expired_holds` every 5 minutes.
- Everyone can browse inventory; only admins change it.

## Sales pipeline (Sprint 7)

- `GET /api/pipeline`: leads grouped by stage with count, value, weighted value and stale count;
  `GET /api/pipeline/forecast`: weighted value of open deals by project and by person;
  `GET /api/pipeline/aged`: open leads quiet for 7+ days. Same visibility as the leads list.
- **Deal value** = estimated value, else the top of the budget, else the bottom. Leads with none are
  counted as "missing value". **Weighted value** = deal value × the stage's probability.
  **Open** = every stage except Booked, Lost and Junk; Booked value is reported separately.
- **Stage probabilities** live in `pipeline_stages` (defaults in `app/models/pipeline.py`); admins edit
  them on the Pipeline page. Booked is fixed at 100%, Lost and Junk at 0%.
- **Days in stage** comes from `leads.status_changed_at`, which an ORM listener on `Lead.status`
  updates whenever the status changes, by hand, by a site visit or by any future module.
- Moving a card uses the normal status rules (`PATCH /api/leads/{id}/pipeline` is the same action as
  `POST /api/leads/{id}/status`): Lost and Junk need a reason; Booked is for managers and admins.
- The board supports mouse and touch dragging (dnd-kit), keyboard moving (focus a card's grip, Space,
  ←/→, Space; Escape cancels) and a "Move to…" menu on every card. Phones open in list view.
- `tests/test_pipeline.py` checks every board and forecast figure against plain SQL on a 60-lead dataset.

## Marketing and reports (Sprint 8)

- **Campaigns** (name, channel, optional project, dates) and **expenses** (date, amount in whole rupees,
  category, vendor) for admins and managers. A lead can be linked to a campaign when it's created or edited.
- **Receipts** (PDF, JPG or PNG, max 10 MB) are checked by their actual content, stored with a random name
  under `FILE_STORAGE_PATH/receipts/`, and only served through `GET /api/expenses/{id}/receipt` to admins
  and managers. They are never in a public folder.
- **Reports** (`/api/reports/{calls|visits|conversion|campaigns|staff}`, periods today/7d/30d/custom):
  every figure's definition is in `app/services/reports.py` and shown on screen under "How these are
  calculated". **Cost per lead = spend ÷ leads attributed to that campaign** (not all leads). Every rate or
  cost is **N/A when its denominator is zero**, never 0%. Deleted leads, and their calls and visits, never count.
- Executives see their own figures only and no campaign report or marketing spend.
  **CSV export** (`/api/reports/{kind}/export`, UTF-8 with BOM for Excel) is for admins and managers, and
  every export is written to the audit log.
- `tests/test_reports.py` checks every report against plain SQL on the demo dataset (with a deleted lead),
  and covers the Phase 2 gate items on cost per lead, N/A and export permissions.

## Incoming enquiries and the inbox (replaces CSV import)

- **Connections** (admin → Connections): one per source: website form, 99acres, MagicBricks, Housing.com,
  Facebook/Instagram lead ads, Google Ads lead forms. Each has its own address (`/api/inbound/{id}`, or
  `/api/inbound/{id}/facebook`) and a secret key that is shown once (only its SHA-256 is stored; "New key"
  replaces it). Facebook's app secret and page token are stored encrypted (key derived from `SECRET_KEY`;
  changing `SECRET_KEY` means re-entering them).
- Keys: `X-Flatons-Key` header, `?key=` in the address (portals), or `google_key` (Google Ads). Facebook is
  verified by its `X-Hub-Signature-256`; lead details are then fetched from the Graph API by the Celery job
  `inbound.facebook_lead` (retries 3 times).
- Website and portals send JSON or form fields with common names (`name`, `mobile`/`phone`/`contact_number`,
  `email`, `city`, `message`/`query`, `project`/`property_name`, `id`/`lead_id`/`query_id`), one at a time or
  as `{"leads": [...]}`. Every request is logged with its raw contents (Connections → Activity), so a portal
  that names fields differently is quick to adapt.
- Rules: a valid phone number is required (otherwise logged as "Not used"); a phone that matches an existing
  lead adds the enquiry to that lead's timeline and alerts its owner (or managers if unassigned); the same
  enquiry re-sent by a platform is recorded once; `?test=true` (or Google's test data) checks without
  creating a lead. Requests over 64 KB are refused.
- **New enquiries** (managers and admins): unassigned open leads, newest first, refreshed every 15 seconds,
  with a live count in the menu. Assigning hands the lead over and notifies the person.
- Platforms only send to **HTTPS** addresses, so live connections need the domain and certificate in place.

## Habitat, cost sheets and customer details

- **Real projects:** `python -m app.cli load-projects` creates **Habitat** (Avnee Estates, Kharadi, Pune; 214 units
  from the Kharadi area statement: 14 shops and 200 co-living/convention rooms, carpet and saleable (lease) areas;
  3.5% commission; the cost sheet template from the developer's PRINT sheet) and **Optimids** (no data yet). The data
  is in `backend/app/data/projects_seed.json`. Safe to run again: it only adds what's missing and never changes
  prices, held or booked units, or anything already entered.
- **Price and area** on each unit: admins and managers enter carpet area, saleable area and rate per sq ft; the price
  is rate x saleable area. Other unit changes stay admin-only.
- **Cost sheet** (`backend/app/services/cost_sheet.py`): cost = rate x chargeable area; GST per stage; furnishing per sq
  ft; stamp duty rounded up to Rs 100; registration % capped; legal and other charges; grand total. The last payment
  stage absorbs rounding so the columns always add up. Admins edit the project template (Projects -> Cost sheet
  settings; stages must total 100%); admins and managers can change any number for one unit (Edit cost sheet).
  **Print cost sheet** opens `/cost-sheet/{unit}` without the menu, ready to print or save as PDF. A booked unit's
  sheet uses the agreed price and shows the customer.
- **Customer details** on a booking (shown in the unit's Customer section and on the booking): name, applicant name,
  mobile, email ID, address, and payment preference: self, or bank payment with bank name, banker contact person and
  phone (bank details only with bank payment, enforced by the database). Editable by managers, admins and the person
  who handled the booking. A unit can be booked straight from its panel (Book this unit, with a lead search).
- **Sources in use:** 99acres, MagicBricks, Housing.com, Meta ads (Facebook / Instagram) and Google Ads, plus offline
  sources (walk-in, referral, channel partner, print, other). "Website" is retired for new leads and connections, and
  website and SMS/email for new campaigns; existing records keep their original value.

### Agreement done and floor plans

- The unit status stored as `sold` is shown everywhere as **Agreement done**. Managers and admins mark a booking's
  agreement done (with its date, not before the booking date or in the future) from the booking page or the unit
  panel: the unit turns Agreement done; **Undo** turns it back to Booked; cancelling the booking still frees the unit.
  The dashboard's project bars show Agreement done and Booked separately.
- **Floor plans** (PDF, JPG, PNG up to 15 MB; checked by content; stored under `FILE_STORAGE_PATH/floor_plans`, served
  only to signed-in staff) are uploaded on the project page by admins and managers, for the whole project, one floor,
  or one unit type. A unit's panel shows the plans for its floor and its type, or the project-wide plans if there
  are none more specific.

## Post-sales (Phase 1, sprint 10): customer inspection, snag register, registration and handover (Stages 13 and 14)

- **Customer inspections** (`possession_inspections`): date, attendees, notes, report shared (date, how); printable
  inspection report `/inspection-report/{case}/{inspection}`.
- **Snag register** (`possession_snags` + `possession_snag_evidence`): SNG id, location, category, severity (minor /
  major / critical), source (internal / customer), owner, target date, issue and completion photos, rectification,
  verification, customer acceptance or dispute, reopen reason and count, closure date. Fixed needs rectification
  details; major/critical need a completion photo; verified by someone other than the fixer; internal snags close on
  verification, customer snags close only on the customer's acceptance (a dispute reopens). New snags withdraw readiness
  approval. Overdue snags are reminded daily (critical ones to CRM managers too).
- **Gate condition 7**: customer inspection done and no open major/critical snag (minor ones may stay open).
- **Possession status** (not ready ... handover completed) with parallel pending items; the four dates kept apart:
  construction completed (milestone verified), possession offered (letter released), legally eligible (gate first
  open), actual possession (handover).
- **Handover checklist** (identity and authorisation, keys, access cards, remotes, parking, meters, utilities, FM and
  emergency contacts, manuals, house rules, acknowledgement, signed checklist from folder 09, photos note); completing it
  needs the open gate, a possession appointment and the required items; locked afterwards.
- **Registration details** on the agreement: signatories, documents produced, receipt reference, original deed custody,
  delivery and the customer's acknowledgement.

## Post-sales (Phase 1, sprint 9): pre-possession and the possession gate (Stage 12)

- **Trigger**: a possession file (`possession_files`) opens once the project's possession milestone is verified
  (Cost sheet settings > Possession; default the last payment stage, e.g. OC); an admin can open it early with a reason.
- **A. Finance**: worked out from the ledger (outstanding, overdue vs demanded-not-yet-due, other charges, unallocated
  payments, loan not disbursed, unconfirmed receipts, open payment/receipt/demand/refund tickets, final stage demanded)
  plus finance's confirmations (authorised charges, adjustments, taxes/deposits/statutory, payment confirmation).
  **Clearance is maker-checker**: finance requests (figures frozen), a finance approver who didn't request it clears it;
  clearing with money outstanding needs a written reason (e.g. payable at possession under the agreement).
- **B. Documents** and **C. Unit readiness**: project-specific checklists (defaults from the specification); N/A and
  issues need a reason; meter readings; snags (`possession_snags`) with rectification owner and due date, verified by
  someone other than the fixer; inspection evidence from folder 09; readiness approved by a project manager/admin only
  when nothing is pending; a new snag withdraws the approval.
- **D. Gate**: legal readiness (project details + registered agreement), documents, finance clearance, unit readiness,
  CRM manager's internal approval, customer informed (possession letter released in folder 09). A "Possession handover"
  appointment can't be scheduled until these are met or covered by an exception (CRM manager/admin: reason, date,
  scope = the conditions it covers).

## Post-sales (Phase 1, sprint 8, part 2): escalation engine, service settings, service reports (Stage 11)

- **Escalation engine** (Celery beat `service.escalations`, every 15 minutes; `services/tickets.run_escalations`):
  level 1 at risk or first response overdue (owner, or CRM managers if unassigned); level 2 resolution breached
  (configured roles, default CRM managers); level 3 breached by more than N hours (default 24; admins and management).
  Each level fires once (reopening starts again); paused and resolution-proposed tickets don't escalate. Each escalation
  is kept (`ticket_escalations`: level, rule, recipients, time) and shown on the ticket.
- **Service settings** (`/service/settings`; `service_settings`; admins edit, others view): response/resolution hours
  per priority, at-risk %, reopen days, each category's team and confirmation rule, escalation recipients. Each ticket
  keeps the window and confirmation rule it was raised under (settings apply to new tickets only).
- **Service reports** (`/service/reports`, `GET /api/service/reports?start=&end=`): raised/closed/open, first response
  and resolution (average, median; resolution excludes paused time), paused time (customer / third party), response and
  resolution breaches, at risk now, escalations by level, reopened, satisfaction (average, responses, 1-5 split); overall,
  by category and by team.

## Post-sales (Phase 1, sprint 8, part 1): customer service tickets (Stage 11)

- **Tickets** (`tickets`, `ticket_events`, `ticket_attachments`; TKT-00001) raised from a case (customer and unit
  linked automatically): the specification's 15 categories, subcategory, title, description, attachments, channel,
  priority. The team comes from the category (e.g. payment -> Finance, defect -> After-sales); CRM managers/admins assign
  an owner. Workflow: raised -> assigned -> acknowledged (first response) -> in progress -> waiting for customer /
  internal team / third party -> resolution proposed -> customer confirmation -> closed (closure reason required).
- **Internal notes** never reach the customer; **messages** (to/from the customer, by channel) are the customer log.
- **Closure rules**: "resolved" needs a proposed resolution; demand, modification, snagging, defect, refund and grievance
  tickets also need the customer's confirmation (with a 1-5 satisfaction score); other reasons need a note. "Not
  satisfied" sends it back to in progress. **Reopen** within 14 days (anyone on the team) or later by a CRM manager/
  admin; the previous closure is kept.
- **SLA** (`services/tickets.py`): response and resolution targets by priority (urgent 2 h / 1 day ... low 2 days /
  15 days); paused while waiting for the customer or a third party (resolution target moves out by exactly the paused
  time; paused hours kept separately); at risk (under 25% of the window left) and breached flags.
- **Service** menu (`/service`, views: open, mine, at risk, breached, closed; category and team filters); ticket page
  (`/service/{id}`); Service tab on each case. Part 2: escalation engine, configurable SLA/category rules, reports.

## Post-sales (Phase 1, sprint 7): construction progress and project communication (Stage 10)

- **Construction progress** on each milestone (`milestone_progress` history; new milestone fields): percentage,
  planned date, phase, tower/building (information only for now), responsible project manager (the first PM to report
  progress, unless set), delay reason + revised expected date (always together), optional photos. A delay notifies CRM
  managers. **Progress never raises a demand**; only verified completion does (the specification's "Important" rule).
- **Schedule impact** (on demands or possession): recorded by a PM/CRM/admin, approved by a CRM manager or admin who
  didn't record it.
- **Customer-facing project updates** (`project_updates`, photos, corrections): written by PM/CRM/post-sales/admin,
  waiting for approval; published by a CRM manager or admin other than the author (or returned with a reason);
  published updates are never edited or deleted: corrections keep the earlier wording, who, when and why. For the
  customer portal when it opens.
- Per-tower milestones and demands for multi-tower projects are left until a multi-tower project's structure is known.
- `nginx/flatons-crm.conf`: upload limit 25 MB (the API allows up to 20 MB); index.html is never cached.

## Post-sales (Phase 1, sprint 6, part 2): the appointment calendar

- **Appointments** (`appointments`; APT-00001) per case: agreement signing, registration, site visit, customer
  inspection, possession handover, defect inspection, document collection, other. Owner (defaults to the case owner),
  date/time, duration, location, documents to bring, notes, customer confirmation (date and how), reschedules (the old
  one kept with its reason; confirmation needed again), cancellation (reason), attendance (outcome) or no-show.
- **Double booking**: an owner with an overlapping appointment gets a 409 unless the booking is confirmed (`allow_clash`).
- **No-show** sets a follow-up for the next day; it shows in Follow-ups due ("Missed appointment") until rescheduled.
- **Calendar** (`/calendar`, `GET /api/calendar?start=&days=&mine=`): appointments, registration appointments from
  agreements (not entered twice) and, for sales roles, sales site visits (executives see their own). Week view; on
  phones a day list, and the Calendar sits in post-sales staff's bottom bar.
- **Daily (09:00)**, to the owner (CRM managers if none): tomorrow's and today's appointments (today's flags unconfirmed
  ones), attendance not recorded, missed-appointment follow-ups. Customer-facing reminders come with the portal.

## Post-sales (Phase 1, sprint 6, part 1): home loan coordination

- **Loans** (`loans`, `loan_doc_requests`, `loan_disbursements`; one open loan per case, closed ones kept with a reason),
  per the specification's Stage 9: lender, application no., customer consent (required before any coordination),
  applied/sanctioned amounts, sanction date and validity, bank RM contact, technical/legal verification, pending
  conditions, follow-up owner and next follow-up date.
- **Workflow** worked out from what's recorded (`services/loans.stage`): details captured -> documents requested ->
  documents submitted -> bank review -> disbursement requested -> awaited -> funds received -> reconciled.
- **Disbursements**: request (never beyond the sanction), acknowledge with an expected date / delay reason, cancel with a
  reason, record funds received (finance: date, amount, UTR) which creates a **loan receipt** in Receipts. It counts
  only when a finance approver confirms it, and demands are never marked paid automatically.
- **Daily (09:00)**: delayed disbursements (owner; CRM managers too from 7 days), loan follow-ups due, sanctions
  expiring in 15/7/1 days. Warnings when the ledger's loan differs from the sanction.
- **Access**: only ledger viewers see loan data; post-sales, CRM, finance and admin edit; finance/admin record funds.

## Post-sales (Phase 1, sprint 5, part 2): the sale agreement workflow

- **Agreements** (`agreements`; AGR-00001; one live per case, cancelled ones kept with a reason), following the
  specification's Stage 4: initiated -> data verified -> drafted (versioned) -> internal review -> (changes requested)
  -> customer review -> execution preparation -> signed & registered -> final uploaded -> released ("completed").
- **Starting conditions are per project** (Cost sheet settings > Agreement): minimum % of the agreement value received
  (confirmed receipts; default 10), KYC approved (on/off), plus an approved ledger.
- **Data checks / discrepancies** (`services/agreements.checks`): legal name and PAN, ownership structure, co-applicant
  PANs, unit areas, booking price = ledger base price, schedule = agreement value and GST, developer legal details.
- **Draft** from the project's clauses (placeholders until Legal supplies approved wording; `{project}`, `{unit_no}`,
  `{agreement_value}` (Indian grouping), `{agreement_no}`): parties, unit, consideration, schedule. `/agreement-draft/{case}`
  prints it, DRAFT-marked until registered. Each new draft is a version; approvals start over.
- **Internal review**: legal and finance (finance approver) both approve; never the drafter; an admin can give one
  side only. Customer review is recorded by staff (portal later). Execution: stamp duty (from the ledger), registration
  fee, appointment, sub-registrar office, ID documents, signing note; registration needs those first.
- **Final upload** goes into folder 03 (linked to the agreement, registration number as document number) for the
  folder's review and release; the agreement shows "Released to customer" once released.

## Post-sales (Phase 1, sprint 5, part 1): the customer document folder

- **Customer folder** (`case_documents`; DOC-00001; files under `FILE_STORAGE_PATH/case_docs`): the specification's 11
  categories (01 Booking & Application ... 11 Other Project Documents). Mandatory metadata: category, type, title,
  number, date, validity, linked reference, uploader and time, verification (pending/verified/rejected/expired),
  approval (under approval/approved/released/withdrawn/rejected), version, visibility (internal/customer), SHA-256.
- **Process**: upload (type/size checked by content; duplicate file or live duplicate number in the category refused)
  -> review by someone other than the uploader (approve or reject with a reason; rejected files stay in the history)
  -> release to the customer (CRM manager/admin) or withdraw (with a reason). A new version needs a reason; a
  released old version is withdrawn automatically. Uploads, reviews, releases, withdrawals and downloads are audited.
- **Who** (`services/case_documents.py`): view by category (KYC: KYC viewers; demands/payments/loan: ledger viewers;
  others: all post-sales roles); upload and review by category (e.g. legal for agreements, finance approver for
  payments/loan/demands, site for construction/possession/warranties).
- Generated documents appear in their folder without being stored twice: KYC files (02), issued/cancelled demand
  letters (04), confirmed receipts and the statement of account (05).
- Not yet: malware scanning (needs a scanner such as ClamAV on the server; planned for hardening).

## Post-sales (Phase 1, sprint 4, part 2): follow-ups, promises to pay, reminders

- **Payment follow-ups** (`payment_follow_ups`): how (call, email, SMS, WhatsApp, visit, letter, note), outcome
  (reached, not reachable, promised to pay, disputed, says already paid, other), note, optional demand, contact date
  (last 30 days), optional next follow-up (next 60 days). Logged by post-sales, CRM, finance or admin; visible to
  ledger viewers. A promise needs an amount and a date in the next 90 days.
- A promise is **kept** when confirmed receipts recorded after it was made, dated by the promise date, reach the
  amount; **broken** once the date passes without that; **open** until then.
- **Daily reminders** (Celery beat `postsales.payment_reminders`, 09:00 India time; `services/followups.run_reminders`)
  to the case owner (or CRM managers if none): issued demands due in 3 days / today / overdue 1, 7, 15, 30 days
  (CRM managers too from 15); broken promises (owner, whoever logged it, CRM managers; once); follow-ups due today.
  The same reminder isn't repeated within 20 hours. Customer-facing SMS/email/WhatsApp come with the portal phase.
- Post-sales home: **Follow-ups due** (follow-ups due, promises due today or broken) via `/api/post-sales/follow-ups/due`.

## Post-sales (Phase 1, sprint 4, part 1): milestones and demands

- **Construction milestones** (`project_milestones`, `milestone_evidence`; files under `FILE_STORAGE_PATH/milestones`):
  the project's payment stages after Booking. Project managers, site staff or admins report one complete with a date
  and 1-10 evidence files; a CRM manager or admin who didn't report it verifies or returns it (with a reason).
- **Verifying** a milestone marks that stage **demanded** today and **due** after the project's "days to pay a
  demand" (cost sheet settings, default 15) in every live booking's ledger, and drafts a demand where the ledger is
  approved. Stages now have `demanded_on` (counts in "currently demanded") and `due_date` (counts as overdue after it).
  Ledger schedule edits keep these dates.
- **Demands** (`demands`; DMD-00001): this stage still unpaid (incl. GST) + earlier demanded stages still unpaid,
  due date. Finance submits (needs the project's legal and bank details complete); a finance approver who didn't
  submit approves or returns. Approval **freezes the letter** (the bank account number kept encrypted). Post-sales,
  CRM, finance or admin record how it was issued. A correction = cancel with a reason (+ a new version); one live
  demand per stage. Payment status (unpaid / part paid / paid / overdue) comes from confirmed receipts.
- **Demand letter**: `/demand-letter/{case}/{demand}` (print or save as PDF); DRAFT-marked until approved.
- Floor plans are now visible to post-sales staff too.

## Post-sales (Phase 1, sprint 3): receipts and reconciliation

- **Receipts** (`receipts`, `receipt_allocations`; RCT-00001): amount, date, mode (cheque, DD, NEFT, RTGS, IMPS,
  UPI, card, cash, other), source (own funds or loan disbursement), payer, reference, bank. Rules: a reference for
  everything but cash; no cash of Rs 2,00,000 or more (Income-tax Act s.269ST; also a database rule); no future
  dates; a live reference can't be recorded twice (a bounced cheque may be presented again); loan disbursements need
  a sanctioned loan on the ledger.
- **Matching**: oldest unpaid stages first by default, or by hand to stages (by stage number) and to statutory/other
  charges. Nothing can be matched beyond what's unpaid (live receipts reserve their matches); the rest is an advance.
  Ledger schedule/charge edits that would fall below matched amounts are refused.
- **Maker-checker**: finance records and matches; a finance approver (never the recorder) confirms. Only confirmed
  receipts count. Approvers mark cheques/DDs **bounced** or confirmed receipts **reversed**, with a reason; nothing is
  deleted. Every step is in the case history and audit log.
- The booking amount becomes a receipt waiting for confirmation when the ledger is generated (and, by migration, for
  ledgers that already existed), using the booking's payment mode and reference.
- Balances now come from confirmed, matched receipts (`services/payments.position`), plus "waiting for confirmation"
  and "advance". **Statement of account**: `/statement/{case}` (print or save as PDF).

## Post-sales (Phase 1, sprint 2): the financial ledger

- One ledger per accepted case (`ledgers`, `ledger_charges`, `ledger_schedule_items`). **Generate** builds a draft
  from the unit's cost sheet at the agreed price: base price, GST, stamp duty, registration, legal, furnishing and
  other charges, plus the project's payment stages (Booking due on the booking date; later stages due on their
  construction milestone). The lender comes from the booking's bank payment details.
- Charge groups: agreement value (base, floor rise, PLC, parking, amenities, discounts as negative amounts), GST,
  statutory (stamp duty, registration), other charges (outside the payment plan).
- Rules before submitting/approving (`services/ledger.problems`): schedule amounts = agreement value; schedule GST =
  GST charge = GST rate x agreement value; loan <= total payable and needs a lender; milestone stages need a name.
- **Maker-checker**: finance executives (and admins) prepare and submit; finance approvers (and admins) approve or
  return with a reason, never their own submission. Approved ledgers are locked; an approver reopens with a reason
  (new version). Every step is in the case history and the audit log; approvers are notified.
- Seven balances (`services/ledger.balances`): total outstanding, currently demanded, overdue (due date passed),
  own contribution still required, loan not yet disbursed, under dispute, other charges. Until receipts arrive the
  booking amount counts as received (own funds); disbursements and disputes are 0 until their modules exist.
- Viewers: admin, CRM manager, post-sales executive, finance, finance approver, management, auditor.

## Post-sales (Phase 1, sprint 1): handover, customer master and KYC

- **Roles** (`app/models/user.py`): besides admin, manager, executive and docs, there are post-sales roles:
  `postsales_exec`, `crm_manager`, `finance`, `finance_approver`, `legal`, `project_manager`, `site`, `service`,
  `after_sales`, `management`, `auditor`. Post-sales roles never see pre-sales leads (API and pages); sales see only a
  booking's post-sales status, never KYC or the customer master. KYC files: admin, CRM manager, post-sales executive,
  legal and auditor only; every view is logged.
- **Case per booking** (`postsales_cases`, PSC-00001): created when a booking is recorded (existing live bookings got
  one in the migration). Post-sales accepts the handover (required: customer name, mobile, unit, agreed price,
  payment plan) or returns it to sales with a reason; sales resends after fixing. Cancelling the booking cancels
  the case.
- **Customer master** (`customer_profiles`, `co_applicants`): ownership type, legal name, PAN, DOB, co-applicants
  with ownership shares (joint: must total 100%), nominee, addresses, language, contact preferences, consents
  (timestamped). Changing identity details after approval sends onboarding back to review.
- **KYC** (`kyc_documents`, files under `FILE_STORAGE_PATH/kyc`): requirements per applicant (PAN, identity,
  address, photo; entity documents for companies, firms, HUFs, trusts). Files checked by content, SHA-256
  fingerprinted, duplicates refused, replacements keep history. The uploader can't verify their own document
  (admins excepted). Onboarding: Not started -> Documents pending -> Under review <-> Clarification required ->
  Approved (OTP verification arrives with the customer portal). Every decision is in `case_events` and the audit log.
- **Project legal and bank details** (admins): legal name, RERA, registered address, signatory, GSTIN, CIN (optional);
  bank account number encrypted (Fernet), shown masked, reveal logged. `GET /api/projects/{id}/doc-readiness` lists
  what's missing; document generation will call `services/doc_readiness.require_ready`.
- Note: PostgreSQL can't remove enum values, so downgrading leaves the added `user_role` values in place (unused).

## Channel partners

- **Channel partners** (left menu): name, company name, contact (mobile, email) and RERA number. Everyone in sales
  can add partners; managers and admins edit or mark them inactive. Mobile and RERA numbers are unique (database
  indexes); RERA numbers are stored in capitals.
- A lead whose source is **Channel partner** can name the partner who brought it (only with that source; switching
  the lead to another source clears it). A booking takes the partner from its lead.
- Each partner's page has two sub-tabs: **Partner details** and **Customers** (every customer they brought, with
  status, project, owner and, once booked, the booking, unit and price). Executives see only their own customers.
- API: `/api/channel-partners` (list with `q` = name, company or RERA), `/{id}`, `/{id}/customers`.

## Frontend notes

- **Left menu (desktop):** the arrow button beside the logo collapses the menu to icons only (names show on hover and
  stay available to screen readers) and expands it again. The choice is remembered in the browser
  (`localStorage` key `flatons.sidebar.collapsed`); when collapsed the page content may grow a little wider. On short
  screens the menu scrolls inside the dark panel. Phones use the bottom bar instead.


- Design tokens (forest green, gold, paper, ink) live in `frontend/src/index.css` under `@theme`.
  Tailwind v4 reads them from CSS, so there is no `tailwind.config.ts`; use them as `bg-forest-900`,
  `text-gold-500`, etc.
- All API calls go through `src/lib/api.ts`. It sends cookies, renews an expired session once
  automatically, and turns API errors into readable messages (`errorMessage()`).
- Pages other than sign-in, the dashboard and "not found" load on first visit (`lazy()` in
  `src/App.tsx`), which keeps the first download small on phones.
- Navigation items and which roles see them are defined in `src/lib/nav.ts`. Pages restricted to
  certain roles are wrapped in `<RequireRole>` in `src/App.tsx`. The API enforces the same rules.

## Environment variables

All configuration is in `backend/.env` (never committed). See `backend/.env.example`
for every variable and its meaning.

## Deployment

The server pulls from GitHub using a read-only deploy key. To deploy the latest `main`:

```bash
sudo -iu crm bash /home/crm/flatons-crm/scripts/deploy.sh
```

This pulls the code, installs backend dependencies, runs migrations, builds the frontend
into `/var/www/flatons-crm`, restarts the services and checks `/api/health`.

Useful commands on the server:

```bash
sudo systemctl status flatons-api flatons-worker flatons-beat
sudo journalctl -u flatons-api -f        # live API logs
sudo nginx -t && sudo systemctl reload nginx
```
