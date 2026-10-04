# Project: Manufacturing Copilot for Odoo

## Goal
Build a portfolio-quality web app on top of an Odoo ERP for a fictional e-bike
drive system manufacturer ("VoltRide Systems"). It helps staff understand
production, spot shortages and take action, with an AI assistant that queries
live ERP data through safe, typed tools.

This is a portfolio project for AI application engineer roles. Code quality,
clear architecture and sensible security matter more than feature count.

## Hosting architecture
```
Vercel (React front end)
   │  /api/* rewrite (same origin, no CORS)
   ▼
Hugging Face Spaces (FastAPI, Docker SDK) ──> LLM API (Anthropic)
   │                    │
   │                    └──> Neon (Postgres: chat history, audit log)
   ▼
Odoo Online (odoo.com trial database) via external API
```

- Front end: Vercel (Hobby plan). `vercel.json` rewrites `/api/*` to the back end.
- Back end: FastAPI in a Docker container on Hugging Face Spaces, listening on
  port 7860. The disk is ephemeral: never store files locally.
- App database: Neon Postgres via `DATABASE_URL`.
- ERP: an Odoo Online trial database (e.g. https://voltride-demo.odoo.com).
  The trial expires after 15 days, so the system must be fully restorable on a
  fresh database (see "Odoo rules").
- Uploaded PDFs are processed in memory and not stored.

## Tech stack
- Front end: React + TypeScript + Vite, Tailwind CSS, TanStack Query,
  React Flow (BOM tree), Recharts (charts)
- Back end: Python 3.12, FastAPI, Pydantic, SQLAlchemy, Alembic
- LLM: Anthropic API with tool calling; model name set via environment variable
- Local development: Docker Compose runs the back end and a local Postgres.
  The front end runs with `npm run dev` and proxies `/api` to the local back end.
  Local development talks to the same Odoo Online database (or a demo snapshot).

## Repository structure
```
/backend
  Dockerfile
  /app
    /api          # FastAPI routers
    /odoo         # Odoo client interface + live and demo implementations
    /services     # business logic: BOM explosion, planning, AI orchestration
    /ai           # tool definitions, tool executors, prompts
    /models       # SQLAlchemy models
    /schemas      # Pydantic schemas
  /scripts
    check_odoo.py        # verifies connection and API access
    seed_odoo.py         # populates a fresh Odoo database
    export_snapshot.py   # exports Odoo data to JSON for demo mode
  /tests
/frontend
  vercel.json
  /src
    /components
    /pages
    /api          # typed API client
docker-compose.yml
.env.example
README.md
```

## Environment variables
```
ODOO_MODE=live            # live | demo
ODOO_URL=https://voltride-demo.odoo.com
ODOO_DB=voltride-demo
ODOO_USER=
ODOO_API_KEY=
DATABASE_URL=
ANTHROPIC_API_KEY=
LLM_MODEL=
DEMO_PASSWORD=            # optional gate for AI features on the public demo
```

## Odoo rules
1. Odoo Online runs a recent SaaS version of Odoo. Do not assume field or model
   names from older versions: inspect the live instance (e.g. `fields_get`)
   before relying on a field, and check which external API protocol the
   instance supports.
2. Use only features available in Odoo Community too: Sales, Inventory,
   Manufacturing (including work centers and work orders) and Purchase.
   No Quality, PLM, Studio or other Enterprise-only modules, so the project can
   later move to Community without changes.
3. All data comes from `seed_odoo.py`. Never rely on data created by hand in the
   web interface. Restoring onto a fresh trial must be: update `.env`, run
   `seed_odoo.py`, done.
4. All Odoo access goes through one interface in `/backend/app/odoo` with two
   implementations:
   - `live`: calls the real Odoo API (with timeouts, retries and clear errors)
   - `demo`: reads a JSON snapshot produced by `export_snapshot.py`
   Selected by `ODOO_MODE`. The public demo must keep working if the trial
   database has expired.
5. Authenticate with the user's login and an API key, never a password.

## Features (in build order)

### Phase 0: Connection check
- `check_odoo.py`: connects to Odoo Online, authenticates, prints the server
  version, confirms read access to key models (res.partner, product.product,
  mrp.bom, stock.quant, sale.order, mrp.production, purchase.order) and confirms
  write access by creating and deleting a test record.
- Report what works and what doesn't before anything else is built.

### Phase 1: Foundation
- Odoo client interface with the live implementation
- `seed_odoo.py`, idempotent (safe to run twice without duplicating data):
  - ~25 components (motors, controllers, cables, displays, sensors, chainrings, casings)
  - 3 finished products (e.g. mid-drive kit, high-power kit, hub motor kit)
  - Multi-level BOMs, with at least one sub-assembly (e.g. controller = PCB + casing + chip)
  - Work centers (e.g. Assembly, Testing) and BOM operations with expected durations
  - Suppliers with prices and lead times
  - Stock levels, deliberately short on some components
  - Sales orders and manufacturing orders in various states
- FastAPI endpoints for dashboard data, with a health check endpoint
- React dashboard: open sales orders, manufacturing orders, low-stock components,
  orders-over-time chart
- Back end Dockerfile ready for Hugging Face Spaces; `vercel.json` with the
  `/api/*` rewrite

### Phase 2: BOM explorer and planner
- Recursive BOM explosion handling multi-level BOMs and guarding against cycles
- Shortage calculation for building N units at every BOM level
- BOM explorer page: React Flow tree, nodes show stock, cost and shortage status
- What-if planner: product + quantity → shortages, bottlenecks, estimated purchase cost
- Unit tests for BOM explosion and shortage logic using fixture data (no live Odoo)
- `export_snapshot.py` and the demo implementation of the Odoo client

### Phase 3: AI assistant (read-only)
- Chat panel with streaming responses and persisted chat history
- Read-only tools, e.g. get_bom_shortages, get_stock_levels,
  get_manufacturing_order, search_products, get_sales_summary
- Must handle questions in English and Chinese

### Phase 4: AI actions and document intake
- Write tools (e.g. draft_purchase_orders) never execute directly: they return a
  proposed action shown as a confirmation card; only the user's confirmation
  executes it, and records are created as drafts
- PDF upload of a supplier quote/invoice: LLM extracts structured JSON, back end
  validates it (totals add up, supplier and products match, no duplicates),
  uncertain fields are flagged, draft purchase order created only after confirmation
- Audit log of every AI tool call: question, tool, parameters, result, timestamp

### Phase 5: Shop floor (MES) view
- Timeline of work orders by work center, planned vs actual duration
- AI-generated daily production summary

### Phase 6: Deployment and polish
- Deploy the back end to Hugging Face Spaces and the front end to Vercel
- Front end shows a friendly "waking up the server" state during cold starts
- Per-IP rate limiting on AI endpoints; optional DEMO_PASSWORD gate
- Error and loading states, responsive layout
- README: architecture diagram (Mermaid), setup and deployment steps, how to
  restore onto a fresh Odoo trial, and a section explaining the AI safety design

## Non-negotiable design rules
1. The LLM never gets raw Odoo access. It can only call tools defined in /backend/app/ai.
2. Validate all tool parameters with Pydantic before executing.
3. Write operations require explicit user confirmation and create drafts only.
4. All secrets come from environment variables (Vercel and Hugging Face secret
   settings in production); provide .env.example; never commit secrets.
5. Keep business logic (BOM explosion, planning) independent of Odoo and the LLM
   so it is testable.

## How to work
- Before writing code for a phase, give me a short plan and wait for my approval.
- Work one phase at a time. At the end of each phase, run the app and tests,
  confirm everything works, and summarise what was built and what I should check.
- If you're unsure how this Odoo version behaves, inspect the live instance
  rather than guessing.
- Explain non-obvious decisions briefly in comments or your summary, since I
  need to explain this project in interviews.
- Commit after each working milestone with clear commit messages.