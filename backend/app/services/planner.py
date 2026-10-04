"""What-if planner: "build N units of X" -> requirements, purchases, bottlenecks.

Pure functions over ManufacturingData; no Odoo, no LLM.

Netting rules (the decisions worth knowing):
- The root is always built in full: the question is "what does building N
  more take", not "how many can I ship from stock".
- Every other product is netted against its *free* stock (on hand minus
  reservations), never raw on-hand, which other orders may already claim.
- Products are processed in low-level-code order, so a component used in
  several branches (the MCU chip in controllers *and* displays) is netted once
  against its total demand instead of each branch double-counting the stock.
- Sub-assembly stock is consumed before building more, so only the remainder
  is exploded into components.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from app.schemas.erp import SupplierPrice
from app.schemas.planning import (
    CapacityLoad,
    MaterialBottleneck,
    NodeStatus,
    PlanResult,
    ProductSummary,
    PurchaseLine,
    Requirement,
    SupplierPurchase,
)
from app.services.bom import ManufacturingData, explode, low_level_codes, unit_costs

EPS = 1e-9

NOTES = [
    "Capacity counts only this plan's work, not manufacturing orders already scheduled.",
    "Lead time is a rough critical-path estimate: supplier lead days plus production time.",
]


@dataclass
class _Line:
    gross: float = 0.0
    from_stock: float = 0.0
    to_build: float = 0.0
    to_buy: float = 0.0
    covered_by_incoming: float = 0.0
    shortage: float = 0.0


def summarize(data: ManufacturingData, product_id: int, unit_cost: float) -> ProductSummary:
    p = data.product(product_id)
    return ProductSummary(
        id=p.id,
        code=p.code,
        name=p.name,
        kind=data.kind(p.id),
        on_hand=p.on_hand,
        free_qty=p.free_qty,
        incoming_qty=p.incoming_qty,
        unit_cost=round(unit_cost, 2),
    )


def net_requirements(
    data: ManufacturingData, product_id: int, quantity: float, *, count_incoming: bool
) -> tuple[dict[int, _Line], dict[int, int]]:
    """MRP netting. Returns per-product lines and each product's low-level code."""
    tree = explode(data, product_id, quantity)
    llc = low_level_codes(tree)
    lines: dict[int, _Line] = defaultdict(_Line)
    lines[product_id].gross = quantity

    for pid in sorted(llc, key=lambda p: (llc[p], p)):
        line = lines[pid]
        product = data.product(pid)
        kind = data.kind(pid)
        # Root is built in full; kits (phantom BOMs) are never held in stock.
        stock_usable = pid != product_id and kind != "kit"
        line.from_stock = min(max(product.free_qty, 0.0), line.gross) if stock_usable else 0.0
        net = _clean(line.gross - line.from_stock)

        if kind == "purchased":
            line.to_buy = net
            line.covered_by_incoming = min(net, max(product.incoming_qty, 0.0)) if count_incoming else 0.0
            line.shortage = _clean(net - line.covered_by_incoming)
        else:
            line.to_build = net
            bom = data.boms[pid]
            for bom_line in bom.lines:
                lines[bom_line.product_id].gross += bom_line.quantity * net / bom.quantity

    return dict(lines), llc


def statuses(data: ManufacturingData, lines: dict[int, _Line], llc: dict[int, int]) -> dict[int, NodeStatus]:
    """Product-level status. 'short' propagates upwards: a sub-assembly that
    must be built from a short component is itself short."""
    result: dict[int, NodeStatus] = {}
    for pid in sorted(llc, key=lambda p: -llc[p]):  # components before parents
        line = lines[pid]
        if data.kind(pid) == "purchased":
            if line.shortage > EPS:
                result[pid] = "short"
            elif line.covered_by_incoming > EPS:
                result[pid] = "incoming"
            else:
                result[pid] = "ok"
        elif line.to_build <= EPS:
            result[pid] = "ok"
        elif any(result[bl.product_id] == "short" for bl in data.boms[pid].lines):
            result[pid] = "short"
        else:
            result[pid] = "build"
    return result


def choose_supplier(suppliers: list[SupplierPrice], qty: float) -> tuple[SupplierPrice | None, float, str | None]:
    """Cheapest vendor whose minimum order fits; else round up to the smallest minimum.

    Returns (supplier, order quantity, note).
    """
    eligible = [s for s in suppliers if s.min_qty <= qty + EPS]
    if eligible:
        return min(eligible, key=lambda s: (s.price, s.lead_days)), qty, None
    if suppliers:
        best = min(suppliers, key=lambda s: (s.min_qty, s.price))
        return best, best.min_qty, f"rounded up to supplier minimum of {best.min_qty:g}"
    return None, qty, "no supplier configured: priced at standard cost"


def plan(data: ManufacturingData, product_id: int, quantity: float, *, count_incoming: bool = True) -> PlanResult:
    lines, llc = net_requirements(data, product_id, quantity, count_incoming=count_incoming)
    status = statuses(data, lines, llc)
    costs = unit_costs(data, set(llc))

    requirements = []
    for pid in sorted(llc, key=lambda p: (llc[p], data.label(p))):
        p, line = data.product(pid), lines[pid]
        requirements.append(
            Requirement(
                product_id=pid,
                code=p.code,
                name=p.name,
                kind=data.kind(pid),
                level=llc[pid],
                gross_qty=_r(line.gross),
                from_stock=_r(line.from_stock),
                to_build=_r(line.to_build),
                to_buy=_r(line.to_buy),
                covered_by_incoming=_r(line.covered_by_incoming),
                shortage=_r(line.shortage),
                status=status[pid],
            )
        )

    purchases, chosen = _purchases(data, lines, costs)
    material = sorted(
        (
            MaterialBottleneck(
                product_id=pid,
                code=data.product(pid).code,
                name=data.product(pid).name,
                shortage=_r(lines[pid].shortage),
                supplier=chosen[pid].supplier if chosen.get(pid) else None,
                lead_days=chosen[pid].lead_days if chosen.get(pid) else None,
            )
            for pid in llc
            if lines[pid].shortage > EPS
        ),
        key=lambda m: (-(m.lead_days if m.lead_days is not None else -1), m.code or m.name),
    )
    capacity = _capacity(data, lines)

    return PlanResult(
        product=summarize(data, product_id, costs[product_id]),
        quantity=quantity,
        count_incoming=count_incoming,
        requirements=requirements,
        purchases=purchases,
        purchase_total=_r(sum(g.total for g in purchases), 2),
        short_count=len(material),
        material_bottlenecks=material,
        capacity=capacity,
        capacity_bottleneck=capacity[0] if capacity else None,
        estimated_days=_r(_critical_path_days(data, product_id, lines, chosen), 1),
        notes=NOTES,
    )


def _purchases(
    data: ManufacturingData, lines: dict[int, _Line], costs: dict[int, float]
) -> tuple[list[SupplierPurchase], dict[int, SupplierPrice | None]]:
    groups: dict[str | None, list[PurchaseLine]] = defaultdict(list)
    chosen: dict[int, SupplierPrice | None] = {}
    for pid, line in lines.items():
        if line.shortage <= EPS:
            continue
        product = data.product(pid)
        supplier, order_qty, note = choose_supplier(product.suppliers, line.shortage)
        chosen[pid] = supplier
        price = supplier.price if supplier else costs[pid]
        groups[supplier.supplier if supplier else None].append(
            PurchaseLine(
                product_id=pid,
                code=product.code,
                name=product.name,
                shortage=_r(line.shortage),
                order_qty=_r(order_qty),
                unit_price=price,
                total=_r(order_qty * price, 2),
                lead_days=supplier.lead_days if supplier else None,
                note=note,
            )
        )
    result = []
    for name, purchase_lines in groups.items():
        leads = [pl.lead_days for pl in purchase_lines if pl.lead_days is not None]
        result.append(
            SupplierPurchase(
                supplier=name,
                lines=sorted(purchase_lines, key=lambda pl: pl.code or pl.name),
                total=_r(sum(pl.total for pl in purchase_lines), 2),
                max_lead_days=max(leads) if leads else None,
            )
        )
    result.sort(key=lambda g: -g.total)
    return result, chosen


def _capacity(data: ManufacturingData, lines: dict[int, _Line]) -> list[CapacityLoad]:
    hours: dict[int, float] = defaultdict(float)
    for pid, line in lines.items():
        bom = data.boms.get(pid)
        if bom is None or line.to_build <= EPS:
            continue
        for op in bom.operations:
            wc = data.work_centers.get(op.workcenter_id)
            efficiency = wc.efficiency if wc and wc.efficiency > 0 else 1.0
            hours[op.workcenter_id] += op.minutes * line.to_build / 60 / efficiency

    def per_day(wc_id: int) -> float:
        wc = data.work_centers.get(wc_id)
        return wc.hours_per_day if wc and wc.hours_per_day > 0 else 8.0

    # Sort on the exact load; rounding first would tie (or misorder) close work centers.
    ranked = sorted(hours, key=lambda wc_id: -hours[wc_id] / per_day(wc_id))
    loads = []
    for wc_id in ranked:
        wc = data.work_centers.get(wc_id)
        loads.append(
            CapacityLoad(
                workcenter_id=wc_id,
                code=wc.code if wc else None,
                name=wc.name if wc else f"Work center {wc_id}",
                hours=_r(hours[wc_id], 1),
                hours_per_day=per_day(wc_id),
                days=_r(hours[wc_id] / per_day(wc_id), 1),
            )
        )
    return loads


def _critical_path_days(
    data: ManufacturingData, root: int, lines: dict[int, _Line], chosen: dict[int, SupplierPrice | None]
) -> float:
    """Longest chain of (supplier lead time -> production steps) to the root."""
    memo: dict[int, float] = {}

    def ready(pid: int) -> float:
        if pid in memo:
            return memo[pid]
        line, bom = lines[pid], data.boms.get(pid)
        if bom is None:
            supplier = chosen.get(pid)
            days = float(supplier.lead_days) if line.shortage > EPS and supplier else 0.0
        elif line.to_build <= EPS:
            days = 0.0
        else:
            inputs = max((ready(bl.product_id) for bl in bom.lines), default=0.0)
            days = inputs + _production_days(data, bom, line.to_build)
        memo[pid] = days
        return days

    return ready(root)


def _production_days(data: ManufacturingData, bom, qty: float) -> float:
    days = 0.0
    for op in bom.operations:  # operations run one after another
        wc = data.work_centers.get(op.workcenter_id)
        per_day = wc.hours_per_day if wc and wc.hours_per_day > 0 else 8.0
        efficiency = wc.efficiency if wc and wc.efficiency > 0 else 1.0
        days += op.minutes * qty / 60 / efficiency / per_day
    return days


def _clean(x: float) -> float:
    return 0.0 if abs(x) < EPS else x


def _r(x: float, digits: int = 4) -> float:
    return round(x + 0.0, digits)
