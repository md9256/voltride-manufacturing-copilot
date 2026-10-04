from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api import dashboard, health
from app.odoo import OdooAuthError, OdooError

app = FastAPI(title="VoltRide Manufacturing Copilot", version="0.1.0")
app.include_router(health.router)
app.include_router(dashboard.router)


@app.exception_handler(OdooError)
def odoo_error_handler(request: Request, exc: OdooError) -> JSONResponse:
    # The ERP behind us failed, not this API: 502 Bad Gateway, with Odoo's
    # message (never its traceback). Auth failures are a server
    # misconfiguration, so the client still gets 502, not 401.
    kind = "odoo_auth" if isinstance(exc, OdooAuthError) else "odoo_error"
    return JSONResponse(status_code=502, content={"error": kind, "detail": str(exc)})
