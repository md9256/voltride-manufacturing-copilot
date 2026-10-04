"""The one interface through which the app reads Odoo.

Two implementations, selected by ODOO_MODE: `live` (calls the JSON-2 API) and
`demo` (reads a JSON snapshot, added in Phase 2). The interface is deliberately
domain-shaped (list_sale_orders) rather than a generic search_read: a generic
query interface would force the demo implementation to re-implement Odoo's
domain language, and would leak Odoo field names into business logic.
"""

from abc import ABC, abstractmethod
from datetime import datetime

from app.schemas.erp import ManufacturingOrder, SaleOrder, StockLevel


class OdooClient(ABC):
    mode: str

    @abstractmethod
    def server_version(self) -> str:
        """Odoo server version string, e.g. '20.0+e'. Doubles as a reachability check."""

    @abstractmethod
    def company_currency(self) -> str:
        """ISO code of the company currency, e.g. 'HKD'."""

    @abstractmethod
    def list_sale_orders(self, since: datetime | None = None) -> list[SaleOrder]:
        """All sale orders (any state), optionally only those ordered on/after `since`."""

    @abstractmethod
    def list_manufacturing_orders(self) -> list[ManufacturingOrder]:
        """All manufacturing orders, newest planned start first."""

    @abstractmethod
    def list_stock_levels(self) -> list[StockLevel]:
        """On-hand vs. reorder minimum for every product that has a reorder rule."""
