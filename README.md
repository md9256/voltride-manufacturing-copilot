# VoltRide Manufacturing Copilot

A web app on top of Odoo for a fictional e-bike drive-system manufacturer:
production dashboard, BOM explorer and planner, and an AI assistant that works
through typed, validated tools. See [SPEC.md](SPEC.md) for the full plan.

> Work in progress. Phase 1 (foundation) is done; the full README with the
> architecture diagram, deployment and AI safety design lands in Phase 6.

## Layout

```
backend/   FastAPI app, Odoo client, seed/check scripts, tests
frontend/  React + TypeScript + Vite dashboard
```

The back end reads Odoo only through the `OdooClient` interface in
`backend/app/odoo` (`live` today, `demo` from Phase 2). Business rules live in
`backend/app/services` as pure functions and are tested without Odoo.

## Local development

Requires Python 3.12+ and Node 20+. Copy `.env.example` to `.env` and fill in
the Odoo URL, database, login and API key (Odoo: avatar > My Preferences >
Account Security > New API Key).

```bash
# Back end
cd backend
python -m venv .venv && .venv/Scripts/activate   # or source .venv/bin/activate
pip install -r requirements-dev.txt
python scripts/check_odoo.py          # connection + permissions check
python -m scripts.seed_odoo           # populate Odoo (safe to re-run)
uvicorn app.main:app --reload         # http://localhost:8000/docs
pytest && ruff check .

# Front end (proxies /api to localhost:8000)
cd frontend
npm install
npm run dev                           # http://localhost:5173
```

With Docker available, `docker compose up` runs the API (and Postgres, used
from Phase 3) instead of the venv.

## Restoring onto a fresh Odoo trial

1. Update `ODOO_URL`, `ODOO_DB` and `ODOO_API_KEY` in `.env`.
2. `python scripts/check_odoo.py`
3. `python -m scripts.seed_odoo`
