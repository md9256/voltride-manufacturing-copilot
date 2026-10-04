"""ERP records returned by the Odoo client interface.

These are our own types, not Odoo's: the live client maps Odoo fields onto
them and the demo client (Phase 2) loads them from a JSON snapshot. Nothing
above /app/odoo ever sees an Odoo field name or a many2one `[id, name]` pair.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

SaleState = Literal["draft", "sent", "sale", "cancel"]
DeliveryStatus = Literal["pending", "started", "partial", "full"]
ProductionState = Literal["draft", "confirmed", "progress", "to_close", "done", "cancel"]


class SaleOrder(BaseModel):
    id: int
    name: str
    customer: str
    state: SaleState
    delivery_status: DeliveryStatus | None  # None until the order is confirmed
    date_order: datetime
    commitment_date: datetime | None
    amount_total: float


class ManufacturingOrder(BaseModel):
    id: int
    name: str
    product_code: str | None
    product_name: str
    quantity: float
    state: ProductionState
    date_start: datetime
    date_finished: datetime | None
    origin: str | None


class StockLevel(BaseModel):
    """On-hand quantity of a product against its reorder rule."""

    product_id: int
    product_code: str | None
    product_name: str
    on_hand: float
    min_qty: float
    max_qty: float


class SupplierPrice(BaseModel):
    """One vendor price line (Odoo product.supplierinfo), in company currency."""

    supplier_id: int
    supplier: str
    price: float
    min_qty: float
    lead_days: int


class Product(BaseModel):
    id: int
    code: str | None
    name: str
    cost: float  # Odoo standard_price
    on_hand: float
    free_qty: float  # on hand minus reservations: what new work can actually use
    incoming_qty: float  # expected receipts (confirmed POs, MO output)
    suppliers: list[SupplierPrice]


class BomLine(BaseModel):
    product_id: int
    quantity: float  # per `Bom.quantity` units of the parent


class BomOperation(BaseModel):
    name: str
    workcenter_id: int
    minutes: float  # per unit produced (Odoo time_cycle_manual, work center capacity 1)


class Bom(BaseModel):
    id: int
    product_id: int
    quantity: float  # batch size the line quantities refer to
    type: Literal["normal", "phantom"]  # phantom = kit, exploded but never stocked
    sequence: int
    lines: list[BomLine]
    operations: list[BomOperation]


class WorkCenter(BaseModel):
    id: int
    code: str | None
    name: str
    hours_per_day: float
    efficiency: float  # 1.0 = 100 %
    cost_per_hour: float
