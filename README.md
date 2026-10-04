# VoltRide Manufacturing Copilot

A web app on top of Odoo for a fictional e-bike drive-system manufacturer:
production dashboard, BOM explorer and planner, and an AI assistant that works
through typed, validated tools. See [SPEC.md](SPEC.md) for the full plan.

> Work in progress. Phases 1-4 (dashboard, BOM explorer, planner, demo mode, AI assistant, confirmed write actions, quote intake, audit log) are done; the full README with the
> architecture diagram, deployment and AI safety design lands in Phase 6.

## Layout

```
backend/   FastAPI app, Odoo client, seed/check scripts, tests
frontend/  React + TypeScript + Vite dashboard
```

The back end reads Odoo only through the `OdooClient` interface in
`backend/app/odoo`: `live` calls Odoo's JSON-2 API, `demo` serves a JSON snapshot
(`ODOO_MODE=demo`), so the public demo survives the Odoo trial expiring. BOM
explosion, MRP netting and the planner live in `backend/app/services` as pure
functions and are tested with fixtures, without Odoo.

## AI assistant

The assistant reads ERP data only through seven typed, read-only tools in
`backend/app/ai/tools.py` (inputs validated with Pydantic before running). It runs on
Google Gemini's free tier by default (`LLM_PROVIDER=gemini`) or on Claude
(`LLM_PROVIDER=anthropic`); chat history is stored in Postgres (Neon) and the
schema is applied by Alembic at startup.

### Writes and quote intake

The assistant can only *propose* draft purchase orders. A proposal is stored and
shown with Confirm / Reject buttons; only the user's Confirm (a separate endpoint
the model cannot call) creates draft RFQs in Odoo, after re-validating the
proposal. Supplier quote PDFs are read by the model into a typed structure, then
checked in plain code (arithmetic, supplier and product matching, prices,
currency, duplicates) before they can become a proposal. Every tool call,
proposal, decision and extraction is written to an append-only audit log.
Sample quotes: `backend/samples/quotes/` (`python -m scripts.make_sample_quotes`).

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
python -m scripts.export_snapshot     # refresh the demo-mode snapshot
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

If the trial has already expired, set `ODOO_MODE=demo`: the app keeps working
from `backend/app/odoo/snapshot/voltride.json`. Refresh that snapshot with
`python -m scripts.export_snapshot` whenever the seed data changes.
