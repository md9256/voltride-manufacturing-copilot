from typing import Annotated

from fastapi import APIRouter, Depends

from app.odoo import OdooClient, OdooError, get_odoo_client
from app.schemas.dashboard import HealthResponse, OdooStatus

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health(odoo: Annotated[OdooClient, Depends(get_odoo_client)]) -> HealthResponse:
    """Always 200 while the API process is up; `status` says whether Odoo is reachable.

    Keeping it 200 lets the host's health probe distinguish "our server is
    down" from "the ERP behind it is down", and the front end can show the
    difference.
    """
    try:
        version = odoo.server_version()
    except OdooError as exc:
        return HealthResponse(status="degraded", odoo=OdooStatus(mode=odoo.mode, reachable=False, error=str(exc)))
    return HealthResponse(status="ok", odoo=OdooStatus(mode=odoo.mode, reachable=True, version=version))
