"""Demo OdooClient: serves a JSON snapshot so the public demo works without Odoo.

Dates are shifted forward by whole weeks since the export, so "orders per
week" and planned start dates stay current months after the trial database
has expired. Whole weeks keep every date on the same weekday.

Writes are simulated: a confirmed draft purchase order gets a DEMO-P#### name
and lives in this process's memory only, so the public demo can show the full
propose -> confirm flow without an ERP behind it.
"""

import itertools
import threading
from datetime import UTC, datetime, timedelta

from app.odoo.base import OdooClient
from app.odoo.snapshot import Snapshot
from app.schemas.erp import (
    Bom,
    ManufacturingOrder,
    Product,
    PurchaseLineDraft,
    PurchaseOrderRef,
    SaleOrder,
    StockLevel,
    SupplierSummary,
    WorkCenter,
    WorkOrder,
)


class DemoOdooClient(OdooClient):
    mode = "demo"

    def __init__(self, snapshot: Snapshot, *, now: datetime | None = None) -> None:
        self._snapshot = snapshot
        self._now = now  # fixed clock for tests; None means real time
        self._simulated_pos: list[PurchaseOrderRef] = []
        self._ids = itertools.count(1)
        self._lock = threading.Lock()

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

    def list_work_orders(self) -> list[WorkOrder]:
        shift = self._shift()
        return [
            w.model_copy(
                update={
                    "date_start": w.date_start + shift if w.date_start else None,
                    "date_finished": w.date_finished + shift if w.date_finished else None,
                }
            )
            for w in self._snapshot.work_orders
        ]

    def list_stock_levels(self) -> list[StockLevel]:
        return list(self._snapshot.stock_levels)

    def list_products(self) -> list[Product]:
        return list(self._snapshot.products)

    def list_boms(self) -> list[Bom]:
        return list(self._snapshot.boms)

    def list_work_centers(self) -> list[WorkCenter]:
        return list(self._snapshot.work_centers)

    def list_suppliers(self) -> list[SupplierSummary]:
        names = {s.supplier_id: s.supplier for p in self._snapshot.products for s in p.suppliers}
        return sorted((SupplierSummary(id=i, name=n, ref=None) for i, n in names.items()), key=lambda s: s.name)

    def find_purchase_orders(
        self, *, supplier_id: int | None = None, origin: str | None = None, partner_ref: str | None = None
    ) -> list[PurchaseOrderRef]:
        return [
            po
            for po in self._simulated_pos
            if (supplier_id is None or po.supplier_id == supplier_id)
            and (origin is None or po.origin == origin)
            and (partner_ref is None or (po.partner_ref or "").lower() == partner_ref.lower())
        ]

    def create_draft_purchase_order(
        self,
        supplier_id: int,
        lines: list[PurchaseLineDraft],
        *,
        origin: str,
        partner_ref: str | None = None,
    ) -> PurchaseOrderRef:
        supplier = next((s.name for s in self.list_suppliers() if s.id == supplier_id), f"Supplier {supplier_id}")
        with self._lock:
            number = next(self._ids)
            po = PurchaseOrderRef(
                id=-number,  # negative: never a real Odoo id
                name=f"DEMO-P{number:04d}",
                supplier_id=supplier_id,
                supplier=supplier,
                partner_ref=partner_ref,
                origin=origin,
                state="draft",
                amount_total=round(sum(line.quantity * line.unit_price for line in lines), 2),
            )
            self._simulated_pos.append(po)
        return po
