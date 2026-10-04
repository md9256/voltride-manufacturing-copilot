"""Odoo access layer. Everything outside this package uses `OdooClient` only."""

from functools import lru_cache
from pathlib import Path

from app.config import get_settings
from app.odoo.base import OdooClient
from app.odoo.demo import DemoOdooClient
from app.odoo.live import LiveOdooClient
from app.odoo.rpc import OdooAuthError, OdooError, OdooRpc
from app.odoo.snapshot import DEFAULT_SNAPSHOT_PATH, load_snapshot

__all__ = ["OdooAuthError", "OdooClient", "OdooError", "get_odoo_client"]


@lru_cache
def get_odoo_client() -> OdooClient:
    """The process-wide client, chosen by ODOO_MODE. Used as a FastAPI dependency."""
    settings = get_settings()
    if settings.odoo_mode == "demo":
        return DemoOdooClient(load_snapshot(Path(settings.odoo_snapshot_path or DEFAULT_SNAPSHOT_PATH)))
    if not (settings.odoo_url and settings.odoo_db and settings.odoo_api_key):
        raise RuntimeError("ODOO_URL, ODOO_DB and ODOO_API_KEY must be set when ODOO_MODE=live")
    rpc = OdooRpc(settings.odoo_url, settings.odoo_db, settings.odoo_api_key, timeout_s=settings.odoo_timeout_s)
    return LiveOdooClient(rpc)
