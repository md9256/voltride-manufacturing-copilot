"""Odoo access layer. Everything outside this package uses `OdooClient` only."""

from functools import lru_cache

from app.config import get_settings
from app.odoo.base import OdooClient
from app.odoo.live import LiveOdooClient
from app.odoo.rpc import OdooAuthError, OdooError, OdooRpc

__all__ = ["OdooAuthError", "OdooClient", "OdooError", "get_odoo_client"]


@lru_cache
def get_odoo_client() -> OdooClient:
    """The process-wide client, chosen by ODOO_MODE. Used as a FastAPI dependency."""
    settings = get_settings()
    if settings.odoo_mode == "demo":
        raise NotImplementedError("ODOO_MODE=demo arrives in Phase 2 (export_snapshot.py + demo client)")
    if not (settings.odoo_url and settings.odoo_db and settings.odoo_api_key):
        raise RuntimeError("ODOO_URL, ODOO_DB and ODOO_API_KEY must be set when ODOO_MODE=live")
    rpc = OdooRpc(settings.odoo_url, settings.odoo_db, settings.odoo_api_key, timeout_s=settings.odoo_timeout_s)
    return LiveOdooClient(rpc)
