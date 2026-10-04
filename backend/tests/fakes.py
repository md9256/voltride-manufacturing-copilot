"""Fixture ERP data and an in-memory OdooClient for API tests."""

from datetime import UTC, datetime

from app.odoo import OdooClient, OdooError
from app.schemas.erp import (
    ManufacturingOrder,
    PurchaseLineDraft,
    PurchaseOrderRef,
    SaleOrder,
    StockLevel,
    SupplierSummary,
)
from tests.factories import mini_voltride


def utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=UTC)


def sale_order(
    id: int, state: str = "sale", delivery: str | None = "pending", when: datetime | None = None, amount: float = 1000.0
) -> SaleOrder:
    return SaleOrder(
        id=id,
        name=f"S{id:05d}",
        customer="Alpine Cycles GmbH",
        state=state,
        delivery_status=delivery,
        date_order=when or utc(2026, 9, 1, 9),
        commitment_date=None,
        amount_total=amount,
    )


def mo(id: int, state: str) -> ManufacturingOrder:
    return ManufacturingOrder(
        id=id,
        name=f"WH/MO/{id:05d}",
        product_code="KIT-MID",
        product_name="Mid-Drive Kit",
        quantity=2,
        state=state,
        date_start=utc(2026, 9, 20, 8),
        date_finished=None,
        origin=None,
    )


def stock(code: str, on_hand: float, min_qty: float) -> StockLevel:
    return StockLevel(
        product_id=sum(map(ord, code)),
        product_code=code,
        product_name=code,
        on_hand=on_hand,
        min_qty=min_qty,
        max_qty=min_qty * 3,
    )


class FakeOdooClient(OdooClient):
    mode = "fake"

    def __init__(self) -> None:
        self.fail = False
        self.sale_orders = [
            sale_order(1, "draft", None, amount=500),
            sale_order(2, "sale", "pending", amount=2000),
            sale_order(3, "sale", "full", amount=9999),
            sale_order(4, "cancel", None, amount=7777),
        ]
        self.mos = [mo(1, "done"), mo(2, "progress"), mo(3, "confirmed"), mo(4, "confirmed")]
        self.levels = [stock("CHP-MCU", 3, 40), stock("PCB-CTL", 40, 20), stock("LCD-35", 0, 15)]
        mini = mini_voltride()
        self.products = list(mini.products.values())
        self.boms = list(mini.boms.values())
        self.work_centers = list(mini.work_centers.values())
        self.purchase_orders: list[PurchaseOrderRef] = []  # existing POs (seeded per test)
        self.created: list[tuple[int, list[PurchaseLineDraft], str, str | None]] = []  # every write
        self.fail_writes = False

    def _check(self) -> None:
        if self.fail:
            raise OdooError("HTTP 503: service unavailable", status=503)

    def server_version(self) -> str:
        self._check()
        return "20.0+e"

    def company_currency(self) -> str:
        return "HKD"

    def list_sale_orders(self, since=None):
        self._check()
        return [o for o in self.sale_orders if since is None or o.date_order >= since.replace(tzinfo=UTC)]

    def list_manufacturing_orders(self):
        self._check()
        return self.mos

    def list_stock_levels(self):
        self._check()
        return self.levels

    def list_products(self):
        self._check()
        return self.products

    def list_boms(self):
        self._check()
        return self.boms

    def list_work_centers(self):
        self._check()
        return self.work_centers

    def list_suppliers(self):
        self._check()
        names = {sp.supplier_id: sp.supplier for p in self.products for sp in p.suppliers}
        return [SupplierSummary(id=i, name=n, ref=None) for i, n in sorted(names.items())]

    def find_purchase_orders(self, *, supplier_id=None, origin=None, partner_ref=None):
        self._check()
        return [
            po
            for po in self.purchase_orders
            if (supplier_id is None or po.supplier_id == supplier_id)
            and (origin is None or po.origin == origin)
            and (partner_ref is None or (po.partner_ref or "").lower() == partner_ref.lower())
        ]

    def create_draft_purchase_order(self, supplier_id, lines, *, origin, partner_ref=None):
        self._check()
        if self.fail_writes:
            raise OdooError("HTTP 500: write failed", status=500)
        self.created.append((supplier_id, lines, origin, partner_ref))
        po = PurchaseOrderRef(
            id=100 + len(self.created),
            name=f"P{100 + len(self.created):05d}",
            supplier_id=supplier_id,
            supplier=next(s.name for s in self.list_suppliers() if s.id == supplier_id),
            partner_ref=partner_ref,
            origin=origin,
            state="draft",
            amount_total=sum(line.quantity * line.unit_price for line in lines),
        )
        self.purchase_orders.append(po)
        return po
