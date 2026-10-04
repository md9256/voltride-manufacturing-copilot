"""Demo OdooClient: serves a JSON snapshot so the public demo works without Odoo.

Dates are shifted forward by whole weeks since the export, so "orders per
week" and planned start dates stay current months after the trial database
has expired. Whole weeks keep every date on the same weekday.
"""

from datetime import UTC, datetime, timedelta

from app.odoo.base import OdooClient
from app.odoo.snapshot import Snapshot
from app.schemas.erp import Bom, ManufacturingOrder, Product, SaleOrder, StockLevel, WorkCenter


class DemoOdooClient(OdooClient):
    mode = "demo"

    def __init__(self, snapshot: Snapshot, *, now: datetime | None = None) -> None:
        self._snapshot = snapshot
        self._now = now  # fixed clock for tests; None means real time

    def _shift(self) -> timedelta:
        now = self._now or datetime.now(UTC)
        weeks = max((now - self._snapshot.exported_at).days // 7, 0)
        return timedelta(weeks=weeks)

    def server_version(self) -> str:
        return f"{self._snapshot.server_version} snapshot"

    def company_currency(self) -> str:
        return self._snapshot.currency

    def list_sale_orders(self, since: datetime | None = None) -> list[SaleOrder]:
        shift = self._shift()
        orders = [
            o.model_copy(
                update={
                    "date_order": o.date_order + shift,
                    "commitment_date": o.commitment_date + shift if o.commitment_date else None,
                }
            )
            for o in self._snapshot.sale_orders
        ]
        return [o for o in orders if since is None or o.date_order >= since]

    def list_manufacturing_orders(self) -> list[ManufacturingOrder]:
        shift = self._shift()
        return [
            o.model_copy(
                update={
                    "date_start": o.date_start + shift,
                    "date_finished": o.date_finished + shift if o.date_finished else None,
                }
            )
            for o in self._snapshot.manufacturing_orders
        ]

    def list_stock_levels(self) -> list[StockLevel]:
        return list(self._snapshot.stock_levels)

    def list_products(self) -> list[Product]:
        return list(self._snapshot.products)

    def list_boms(self) -> list[Bom]:
        return list(self._snapshot.boms)

    def list_work_centers(self) -> list[WorkCenter]:
        return list(self._snapshot.work_centers)
