# Flatons CRM

Lead management, inventory, bookings and post-sales document engine for Flatons.

- **Backend:** Python 3.12, FastAPI, SQLAlchemy (async) + Alembic, PostgreSQL 16, Celery + Redis
- **Frontend:** React 19, TypeScript, Vite (Tailwind added in Sprint 1)
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
```

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
