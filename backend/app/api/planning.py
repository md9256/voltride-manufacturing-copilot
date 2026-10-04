"""BOM explorer and what-if planner endpoints."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query

from app.odoo import OdooClient, get_odoo_client
from app.schemas.planning import BomTreeNode, PlanRequest, PlanResult, ProductSummary
from app.services.bom import BomError, ExplodedNode, ManufacturingData, explode, iter_nodes, unit_costs
from app.services.planner import net_requirements, plan, statuses, summarize

router = APIRouter(prefix="/api", tags=["planning"])

Odoo = Annotated[OdooClient, Depends(get_odoo_client)]


def manufacturing_data(odoo: Odoo) -> ManufacturingData:
    return ManufacturingData.build(odoo.list_products(), odoo.list_boms(), odoo.list_work_centers())


Data = Annotated[ManufacturingData, Depends(manufacturing_data)]


@router.get("/products", response_model=list[ProductSummary])
def list_products(data: Data, kind: Literal["manufactured", "kit", "purchased"] | None = None) -> list[ProductSummary]:
    ids = [pid for pid in data.products if kind is None or data.kind(pid) == kind]
    costs = unit_costs(data, set(ids))
    summaries = [summarize(data, pid, costs[pid]) for pid in ids]
    return sorted(summaries, key=lambda s: (s.code or "", s.name))


@router.get("/bom/{product_id}/tree", response_model=BomTreeNode)
def bom_tree(data: Data, product_id: int, quantity: Annotated[float, Query(gt=0, le=10_000)] = 1) -> BomTreeNode:
    data.product(product_id)  # 404 for an unknown product
    if product_id not in data.boms:
        raise BomError(f"{data.label(product_id)} is purchased, it has no bill of materials")
    tree = explode(data, product_id, quantity)
    # Status comes from the full netting so the tree agrees with the planner.
    lines, llc = net_requirements(data, product_id, quantity, count_incoming=True)
    status = statuses(data, lines, llc)
    costs = unit_costs(data, {n.product_id for n in iter_nodes(tree)})

    def to_schema(node: ExplodedNode) -> BomTreeNode:
        p = data.products[node.product_id]
        return BomTreeNode(
            product_id=p.id,
            code=p.code,
            name=p.name,
            kind=data.kind(p.id),
            level=node.level,
            qty_per_unit=round(node.qty_per_unit, 4),
            quantity=round(node.quantity, 4),
            on_hand=p.on_hand,
            free_qty=p.free_qty,
            unit_cost=round(costs[p.id], 2),
            status=status[p.id],
            children=[to_schema(c) for c in node.children],
        )

    return to_schema(tree)


@router.post("/planner/plan", response_model=PlanResult)
def run_plan(data: Data, request: PlanRequest) -> PlanResult:
    return plan(data, request.product_id, request.quantity, count_incoming=request.count_incoming)
