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

### Business figures (managers and admins, Team view)

- **Leads generated**: leads created in the period. **Leads booked**: leads that moved to Booked in the period.
- **Commission revenue (estimated)**: for each booked lead, deal value (estimated value, else top of budget,
  else bottom) × its project's **Flatons commission %** (set by admins on each project, 0–100).
- **Marketing expense**: expenses dated in the period. **Estimated profit** = revenue − expense (shown as a
  loss in red when negative).
- Booked leads that can't be valued (no project, no commission % on the project, or no value or budget) are
  left out of revenue and counted separately on screen. From Sprint 11, real booking prices replace the
  estimated deal value. Executives, and anyone's "Mine" view, never see these figures.

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

## Frontend notes

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
