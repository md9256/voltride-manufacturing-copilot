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
