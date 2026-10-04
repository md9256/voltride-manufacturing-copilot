"""Request/response schemas for the BOM explorer and what-if planner."""

from typing import Literal

from pydantic import BaseModel, Field

# manufactured: has a normal BOM. kit: phantom BOM, exploded but never stocked.
# purchased: no BOM, bought from suppliers.
ProductKind = Literal["manufactured", "kit", "purchased"]

# ok: covered by free stock. build: will be manufactured, inputs available.
# incoming: purchase shortage covered by expected receipts. short: must be bought
# (or, for a manufactured item, something beneath it is short).
NodeStatus = Literal["ok", "build", "incoming", "short"]


class ProductSummary(BaseModel):
    id: int
    code: str | None
    name: str
    kind: ProductKind
    on_hand: float
    free_qty: float
    incoming_qty: float
    unit_cost: float  # purchased: standard cost; made: rolled-up material + labour


class BomTreeNode(BaseModel):
    product_id: int
    code: str | None
    name: str
    kind: ProductKind
    level: int
    qty_per_unit: float  # per one unit of the root product
    quantity: float  # for the requested root quantity, this branch only
    on_hand: float
    free_qty: float
    unit_cost: float
    status: NodeStatus  # product-level result of the plan, shared by all branches
    children: list["BomTreeNode"]


class PlanRequest(BaseModel):
    product_id: int
    quantity: float = Field(gt=0, le=10_000)
    count_incoming: bool = True  # treat expected receipts as available


class Requirement(BaseModel):
    """One product's line in the plan, after netting across all branches."""

    product_id: int
    code: str | None
    name: str
    kind: ProductKind
    level: int  # low-level code: deepest BOM level the product appears at
    gross_qty: float
    from_stock: float
    to_build: float
    to_buy: float  # shortage against free stock
    covered_by_incoming: float
    shortage: float  # what still has to be ordered
    status: NodeStatus


class PurchaseLine(BaseModel):
    product_id: int
    code: str | None
    name: str
    shortage: float
    order_qty: float  # may be rounded up to the supplier's minimum
    unit_price: float
    total: float
    lead_days: int | None
    note: str | None = None


class SupplierPurchase(BaseModel):
    supplier: str | None  # None: no vendor configured
    lines: list[PurchaseLine]
    total: float
    max_lead_days: int | None


class MaterialBottleneck(BaseModel):
    product_id: int
    code: str | None
    name: str
    shortage: float
    supplier: str | None
    lead_days: int | None


class CapacityLoad(BaseModel):
    workcenter_id: int
    code: str | None
    name: str
    hours: float
    hours_per_day: float
    days: float


class PlanResult(BaseModel):
    product: ProductSummary
    quantity: float
    count_incoming: bool
    requirements: list[Requirement]
    purchases: list[SupplierPurchase]
    purchase_total: float
    short_count: int
    material_bottlenecks: list[MaterialBottleneck]
    capacity: list[CapacityLoad]
    capacity_bottleneck: CapacityLoad | None
    estimated_days: float
    notes: list[str]
