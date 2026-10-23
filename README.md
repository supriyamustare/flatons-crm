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

## Frontend notes

- Design tokens (forest green, gold, paper, ink) live in `frontend/src/index.css` under `@theme`.
  Tailwind v4 reads them from CSS, so there is no `tailwind.config.ts`; use them as `bg-forest-900`,
  `text-gold-500`, etc.
- All API calls go through `src/lib/api.ts`. It sends cookies, renews an expired session once
  automatically, and turns API errors into readable messages (`errorMessage()`).
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
