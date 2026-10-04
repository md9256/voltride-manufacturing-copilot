"""Bill-of-materials structure: lookup, multi-level explosion, rolled-up cost.

Pure functions over ERP records, independent of Odoo and the LLM.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.schemas.erp import Bom, Product, WorkCenter
from app.schemas.planning import ProductKind


class BomError(ValueError):
    """The BOM data cannot be planned with (cycle, dangling reference, ...)."""


class BomCycleError(BomError):
    def __init__(self, path: list[str]) -> None:
        self.path = path
        super().__init__("BOM cycle: " + " -> ".join(path))


class UnknownProductError(BomError):
    def __init__(self, product_id: int) -> None:
        self.product_id = product_id
        super().__init__(f"unknown product {product_id}")


@dataclass
class ManufacturingData:
    """Everything planning needs, indexed for lookup."""

    products: dict[int, Product]
    boms: dict[int, Bom]  # product id -> the BOM used to make it
    work_centers: dict[int, WorkCenter]

    @classmethod
    def build(cls, products: list[Product], boms: list[Bom], work_centers: list[WorkCenter]) -> ManufacturingData:
        chosen: dict[int, Bom] = {}
        # Like Odoo's own BOM lookup: with several BOMs for one product,
        # the lowest sequence (then oldest) wins.
        for bom in sorted(boms, key=lambda b: (b.sequence, b.id)):
            chosen.setdefault(bom.product_id, bom)
        return cls({p.id: p for p in products}, chosen, {w.id: w for w in work_centers})

    def product(self, product_id: int) -> Product:
        try:
            return self.products[product_id]
        except KeyError:
            raise UnknownProductError(product_id) from None

    def kind(self, product_id: int) -> ProductKind:
        bom = self.boms.get(product_id)
        if bom is None:
            return "purchased"
        return "kit" if bom.type == "phantom" else "manufactured"

    def label(self, product_id: int) -> str:
        p = self.products.get(product_id)
        return (p.code or p.name) if p else f"#{product_id}"


@dataclass
class ExplodedNode:
    product_id: int
    level: int
    qty_per_unit: float  # per one unit of the root
    quantity: float  # for the requested root quantity
    children: list[ExplodedNode] = field(default_factory=list)


def explode(data: ManufacturingData, product_id: int, quantity: float) -> ExplodedNode:
    """Expand a product into its full multi-level BOM tree (gross quantities, no netting).

    Raises BomCycleError if a product (indirectly) contains itself; the error
    carries the offending path, e.g. KIT-A -> SA-B -> KIT-A.
    """
    data.product(product_id)  # fail fast on an unknown root

    def walk(pid: int, level: int, per_unit: float, path: tuple[int, ...]) -> ExplodedNode:
        node = ExplodedNode(pid, level, per_unit, per_unit * quantity)
        bom = data.boms.get(pid)
        if bom is None:
            return node
        for line in bom.lines:
            if line.product_id in path or line.product_id == pid:
                raise BomCycleError([data.label(p) for p in (*path, pid, line.product_id)])
            if line.product_id not in data.products:
                # Bad data (e.g. an archived component), not a bad request: BomError, not UnknownProductError.
                raise BomError(f"BOM of {data.label(pid)} references unknown product {line.product_id}")
            child_per_unit = per_unit * line.quantity / bom.quantity
            node.children.append(walk(line.product_id, level + 1, child_per_unit, (*path, pid)))
        return node

    return walk(product_id, 0, 1.0, ())


def iter_nodes(node: ExplodedNode):
    yield node
    for child in node.children:
        yield from iter_nodes(child)


def low_level_codes(tree: ExplodedNode) -> dict[int, int]:
    """Deepest level at which each product appears.

    Processing products in this order guarantees every parent is handled
    before any of its components, so a shared component's demand from all
    branches is known before it is netted against stock (classic MRP).
    """
    codes: dict[int, int] = {}
    for node in iter_nodes(tree):
        codes[node.product_id] = max(codes.get(node.product_id, 0), node.level)
    return codes


def unit_costs(data: ManufacturingData, product_ids: set[int]) -> dict[int, float]:
    """Per-unit cost: purchased items at standard cost; made items rolled up
    from their components plus operation labour at work-center rates."""
    memo: dict[int, float] = {}

    def cost(pid: int, path: tuple[int, ...]) -> float:
        if pid in memo:
            return memo[pid]
        if pid in path:
            raise BomCycleError([data.label(p) for p in (*path, pid)])
        bom = data.boms.get(pid)
        if bom is None:
            memo[pid] = data.product(pid).cost
            return memo[pid]
        material = sum(line.quantity * cost(line.product_id, (*path, pid)) for line in bom.lines) / bom.quantity
        labour = 0.0
        for op in bom.operations:
            wc = data.work_centers.get(op.workcenter_id)
            if wc:
                labour += op.minutes / 60 / (wc.efficiency or 1) * wc.cost_per_hour
        memo[pid] = material + labour
        return memo[pid]

    return {pid: cost(pid, ()) for pid in product_ids}
