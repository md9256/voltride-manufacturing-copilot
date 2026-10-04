import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api import actions, audit, auth, chat, dashboard, health, intake, planning, shopfloor
from app.config import get_settings
from app.models.migrate import upgrade_to_head
from app.odoo import OdooAuthError, OdooError
from app.services.bom import BomCycleError, BomError, UnknownProductError

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Apply pending migrations on startup: one container, one instance, so
    # there is no race between replicas. Without a database the rest of the
    # API still works and the chat endpoints report themselves unavailable.
    if get_settings().database_url:
        await asyncio.to_thread(upgrade_to_head)
    else:
        log.warning("DATABASE_URL not set: chat history is disabled")
    yield


app = FastAPI(title="VoltRide Manufacturing Copilot", version="1.0.0", lifespan=lifespan)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    # The API only serves JSON / event streams: forbid MIME sniffing, framing
    # and referrer leakage. (The front end's headers are set in vercel.json.)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Cache-Control", "no-store")
    return response


app.include_router(health.router)
app.include_router(auth.router)
app.include_router(dashboard.router)
app.include_router(planning.router)
app.include_router(chat.router)
app.include_router(actions.router)
app.include_router(audit.router)
app.include_router(intake.router)
app.include_router(shopfloor.router)


@app.exception_handler(OdooError)
def odoo_error_handler(request: Request, exc: OdooError) -> JSONResponse:
    # The ERP behind us failed, not this API: 502 Bad Gateway, with Odoo's
    # message (never its traceback). Auth failures are a server
    # misconfiguration, so the client still gets 502, not 401.
    kind = "odoo_auth" if isinstance(exc, OdooAuthError) else "odoo_error"
    return JSONResponse(status_code=502, content={"error": kind, "detail": str(exc)})


@app.exception_handler(BomError)
def bom_error_handler(request: Request, exc: BomError) -> JSONResponse:
    # Unknown product: 404. Bad BOM data (e.g. a cycle) or a purchased product
    # asked for its tree: 422, with the reason (cycle path included).
    if isinstance(exc, UnknownProductError):
        return JSONResponse(status_code=404, content={"error": "unknown_product", "detail": str(exc)})
    kind = "bom_cycle" if isinstance(exc, BomCycleError) else "bom_error"
    return JSONResponse(status_code=422, content={"error": kind, "detail": str(exc)})
