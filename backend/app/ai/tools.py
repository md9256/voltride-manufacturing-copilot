"""The assistant's tools: the only way the LLM can reach ERP data.

Design rules this module enforces:
- The LLM never gets raw Odoo access. Each tool is a narrow, read-only
  question answered through the OdooClient interface and the planning
  services, returning a compact JSON result.
- Every tool input is a Pydantic model. The JSON schema sent to the LLM is
  generated from it, and the raw arguments the LLM produces are validated
  against it again before anything runs: a schema in a prompt is a request,
  not a guarantee.
- Failures the model can recover from (unknown product, ambiguous name,
  invalid arguments) come back as error results it can read and act on,
  never as exceptions that end the conversation.
- No tool writes to the ERP. draft_purchase_orders only *builds* a proposal;
  the chat loop stores it and shows it to the user, and only the user's
  confirmation (a separate endpoint the model cannot call) executes it.
"""

from __future__ import annotations

import difflib
import json
import threading
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.odoo import OdooClient, OdooError
from app.schemas.actions import PurchaseProposal
from app.schemas.erp import Product
from app.services import dashboard as dash_rules
from app.services.bom import BomError, ManufacturingData, explode, unit_costs
from app.services.planner import plan
from app.services.purchasing import LineRequest, ProposalError, build_proposal, proposal_for_shortages


class ToolError(Exception):
    """A problem the model should be told about (and can usually fix)."""


class ToolContext:
    """Per-turn access to ERP data. The catalogue is fetched once per turn and
    shared by that turn's tool calls, which run in parallel threads; the lock
    makes the first caller fetch while the others wait for its result."""

    def __init__(self, odoo: OdooClient) -> None:
        self.odoo = odoo
        self._lock = threading.Lock()
        self._data: ManufacturingData | None = None
        self._currency: str | None = None

    @property
    def data(self) -> ManufacturingData:
        with self._lock:
            if self._data is None:
                self._data = ManufacturingData.build(
                    self.odoo.list_products(), self.odoo.list_boms(), self.odoo.list_work_centers()
                )
            return self._data

    @property
    def currency(self) -> str:
        with self._lock:
            if self._currency is None:
                self._currency = self.odoo.company_currency()
            return self._currency


class _Input(BaseModel):
    # Unknown arguments are an error, not silently ignored.
    model_config = ConfigDict(extra="forbid")


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    input_model: type[_Input]
    handler: Callable[[ToolContext, Any], dict | PurchaseProposal]

    def json_schema(self) -> dict:
        schema = self.input_model.model_json_schema()
        schema.pop("title", None)
        return schema


@dataclass
class ToolOutcome:
    ok: bool
    content: str  # JSON text sent back to the model
    summary: str  # one line for the UI
    proposal: PurchaseProposal | None = None  # set by write tools; persisted by the chat loop


# --------------------------------------------------------------------------
# Product resolution: the model may say "KIT-MID", "kit-mid" or "mid-drive kit".
# --------------------------------------------------------------------------


def resolve_product(data: ManufacturingData, ref: str) -> Product:
    ref_l = ref.strip().lower()
    products = list(data.products.values())
    for match in (
        lambda p: (p.code or "").lower() == ref_l,
        lambda p: p.name.lower() == ref_l,
        lambda p: ref_l in (p.code or "").lower() or ref_l in p.name.lower(),
    ):
        found = [p for p in products if match(p)]
        if len(found) == 1:
            return found[0]
        if len(found) > 1:
            options = ", ".join(f"{p.code} ({p.name})" for p in found[:8])
            raise ToolError(f"'{ref}' matches several products: {options}. Use an exact product code.")
    labels = [p.code or p.name for p in products] + [p.name for p in products]
    close = difflib.get_close_matches(ref, labels, n=5, cutoff=0.5)
    hint = f" Did you mean: {', '.join(close)}?" if close else " Use search_products to find codes."
    raise ToolError(f"No product matches '{ref}'.{hint}")


def _product_row(data: ManufacturingData, p: Product, cost: float | None = None) -> dict:
    row = {
        "code": p.code,
        "name": p.name,
        "kind": data.kind(p.id),
        "on_hand": p.on_hand,
        "free": p.free_qty,
        "incoming": p.incoming_qty,
    }
    if cost is not None:
        row["unit_cost"] = round(cost, 2)
    return row


# --------------------------------------------------------------------------
# Tools
# --------------------------------------------------------------------------


class SearchProductsInput(_Input):
    query: str = Field(min_length=1, max_length=80, description="Text to match against product codes and names.")
    kind: Literal["manufactured", "kit", "purchased"] | None = Field(
        None, description="Only manufactured items (kits, sub-assemblies) or purchased components."
    )
    limit: int = Field(10, ge=1, le=25)


def search_products(ctx: ToolContext, args: SearchProductsInput) -> dict:
    data = ctx.data
    words = args.query.lower().split()
    hits = [
        p
        for p in data.products.values()
        if (args.kind is None or data.kind(p.id) == args.kind)
        and all(w in f"{p.code or ''} {p.name}".lower() for w in words)
    ]
    hits.sort(key=lambda p: p.code or p.name)
    costs = unit_costs(data, {p.id for p in hits[: args.limit]})
    return {
        "currency": ctx.currency,
        "match_count": len(hits),
        "products": [_product_row(data, p, costs[p.id]) for p in hits[: args.limit]],
    }


class StockLevelsInput(_Input):
    products: list[str] | None = Field(
        None,
        max_length=30,
        description="Product codes or names. Omit to get every product that has a reorder rule.",
    )
    only_below_reorder_min: bool = Field(False, description="Only products below their reorder minimum.")


def get_stock_levels(ctx: ToolContext, args: StockLevelsInput) -> dict:
    data = ctx.data
    rules = {lvl.product_id: lvl for lvl in ctx.odoo.list_stock_levels()}
    if args.products:
        selected = [resolve_product(data, ref) for ref in args.products]
    else:
        selected = [data.products[pid] for pid in rules if pid in data.products]
    rows = []
    for p in selected:
        row = _product_row(data, p)
        rule = rules.get(p.id)
        row["reorder_min"] = rule.min_qty if rule else None
        row["below_reorder_min"] = bool(rule and p.on_hand < rule.min_qty)
        if not args.only_below_reorder_min or row["below_reorder_min"]:
            rows.append(row)
    rows.sort(key=lambda r: r["code"] or r["name"])
    return {
        "note": "free = on hand minus quantities reserved for existing orders; incoming = expected receipts",
        "products": rows,
    }


class BomInput(_Input):
    product: str = Field(description="Code or name of a manufactured product, e.g. KIT-MID.")
    levels: int = Field(1, ge=1, le=5, description="How many BOM levels to expand.")


def get_bom(ctx: ToolContext, args: BomInput) -> dict:
    data = ctx.data
    product = resolve_product(data, args.product)
    if product.id not in data.boms:
        raise ToolError(f"{product.code} is a purchased component; it has no bill of materials.")
    tree = explode(data, product.id, 1)
    costs = unit_costs(data, set(data.products))

    def node(n, depth: int) -> dict:
        p = data.products[n.product_id]
        out = {"code": p.code, "name": p.name, "qty_per_unit": round(n.qty_per_unit, 4), "kind": data.kind(p.id)}
        if n.children and depth < args.levels:
            out["components"] = [node(c, depth + 1) for c in n.children]
        elif n.children:
            out["components_not_shown"] = len(n.children)
        return out

    return {
        "product": product.code,
        "name": product.name,
        "currency": ctx.currency,
        "rolled_up_unit_cost": round(costs[product.id], 2),
        "components": [node(c, 1) for c in tree.children],
    }


class BomShortagesInput(_Input):
    product: str = Field(description="Code or name of the manufactured product to build, e.g. KIT-HP.")
    quantity: float = Field(gt=0, le=10_000, description="Number of units to build.")
    count_incoming: bool = Field(True, description="Treat expected receipts (open purchase orders) as available.")


def get_bom_shortages(ctx: ToolContext, args: BomShortagesInput) -> dict:
    data = ctx.data
    product = resolve_product(data, args.product)
    if product.id not in data.boms:
        raise ToolError(f"{product.code} is purchased, not manufactured; there is nothing to build.")
    result = plan(data, product.id, args.quantity, count_incoming=args.count_incoming)
    lead = {m.product_id: (m.supplier, m.lead_days) for m in result.material_bottlenecks}
    return {
        "product": product.code,
        "quantity": args.quantity,
        "currency": ctx.currency,
        "can_build_from_stock": result.short_count == 0,
        "short_components": [
            {
                "code": r.code,
                "name": r.name,
                "needed": r.gross_qty,
                "free_stock_used": r.from_stock,
                "covered_by_incoming": r.covered_by_incoming,
                "short": r.shortage,
                "supplier": lead.get(r.product_id, (None, None))[0],
                "lead_days": lead.get(r.product_id, (None, None))[1],
            }
            for r in result.requirements
            if r.shortage > 0
        ],
        "covered_by_incoming": [
            {"code": r.code, "quantity": r.covered_by_incoming}
            for r in result.requirements
            if r.covered_by_incoming > 0 and r.shortage == 0
        ],
        "subassemblies_to_build": [
            {"code": r.code, "name": r.name, "to_build": r.to_build}
            for r in result.requirements
            if r.to_build > 0 and r.product_id != product.id
        ],
        "estimated_purchase_cost": result.purchase_total,
        "work_center_load": [{"work_center": c.name, "hours": c.hours, "days": c.days} for c in result.capacity],
        "estimated_lead_time_days": result.estimated_days,
        "caveats": result.notes,
    }


class ManufacturingOrderInput(_Input):
    reference: str = Field(min_length=1, max_length=40, description="MO number such as WH/MO/00003 or just 00003 or 3.")


def _mo_row(o) -> dict:
    return {
        "reference": o.name,
        "product": o.product_code,
        "product_name": o.product_name,
        "quantity": o.quantity,
        "state": o.state,
        "planned_start": o.date_start.date().isoformat(),
        "finished": o.date_finished.date().isoformat() if o.state == "done" and o.date_finished else None,
        "source": o.origin,
    }


def get_manufacturing_order(ctx: ToolContext, args: ManufacturingOrderInput) -> dict:
    ref = args.reference.strip().upper()
    orders = ctx.odoo.list_manufacturing_orders()
    digits = ref.lstrip("0") if ref.isdigit() else None
    for o in orders:
        number = o.name.rsplit("/", 1)[-1]
        if o.name.upper() == ref or number == ref or (digits and number.lstrip("0") == digits):
            return _mo_row(o)
    known = ", ".join(o.name for o in orders[:10])
    raise ToolError(f"No manufacturing order '{args.reference}'. Recent orders: {known}.")


class ManufacturingOrdersInput(_Input):
    states: list[Literal["draft", "confirmed", "progress", "to_close", "done", "cancel"]] | None = Field(
        None, description="Filter by state. Omit for all orders."
    )
    limit: int = Field(20, ge=1, le=50)


def list_manufacturing_orders(ctx: ToolContext, args: ManufacturingOrdersInput) -> dict:
    orders = ctx.odoo.list_manufacturing_orders()
    selected = [o for o in orders if not args.states or o.state in args.states]
    return {
        "count_by_state": dict(Counter(o.state for o in orders)),
        "orders": [_mo_row(o) for o in selected[: args.limit]],
        "truncated": len(selected) > args.limit,
    }


class SalesSummaryInput(_Input):
    weeks: int = Field(8, ge=1, le=52, description="How many recent weeks to cover for the trend.")


def get_sales_summary(ctx: ToolContext, args: SalesSummaryInput) -> dict:
    today = datetime.now(UTC).date()
    orders = ctx.odoo.list_sale_orders()
    open_orders = dash_rules.open_sale_orders(orders)
    window_start = dash_rules.orders_window_start(weeks=args.weeks, today=today).replace(tzinfo=UTC)
    confirmed = [o for o in orders if o.state == "sale" and o.date_order >= window_start]
    by_customer = Counter()
    for o in confirmed:
        by_customer[o.customer] += o.amount_total
    return {
        "currency": ctx.currency,
        "today": today.isoformat(),
        "open_orders": {
            "count": len(open_orders),
            "value": round(sum(o.amount_total for o in open_orders), 2),
            "quotations": sum(o.state in dash_rules.QUOTATION_STATES for o in open_orders),
        },
        "weekly_confirmed": [
            {"week_start": w.week_start.isoformat(), "orders": w.order_count, "revenue": w.revenue}
            for w in dash_rules.orders_over_time(orders, weeks=args.weeks, today=today)
        ],
        "top_customers": [{"customer": c, "revenue": round(v, 2)} for c, v in by_customer.most_common(5)],
        "open_order_list": [
            {
                "reference": o.name,
                "customer": o.customer,
                "state": "quotation" if o.state in dash_rules.QUOTATION_STATES else "confirmed",
                "delivery": o.delivery_status,
                "date": o.date_order.date().isoformat(),
                "total": o.amount_total,
            }
            for o in open_orders[:15]
        ],
    }


class ShortagesFor(_Input):
    product: str = Field(description="Manufactured product to build, e.g. KIT-MID.")
    quantity: float = Field(gt=0, le=10_000)
    count_incoming: bool = Field(True, description="Treat expected receipts as available (order less).")


class DraftLine(_Input):
    product: str = Field(description="Code or name of a purchased component.")
    quantity: float = Field(gt=0, le=100_000)
    supplier: str | None = Field(None, description="Supplier name. Omit to use the cheapest suitable supplier.")


class DraftPurchaseOrdersInput(_Input):
    shortages_for: ShortagesFor | None = Field(
        None, description="Order exactly the components that are short for building this quantity."
    )
    lines: list[DraftLine] | None = Field(None, max_length=30, description="Or: explicit components and quantities.")

    @model_validator(mode="after")
    def exactly_one(self):
        if (self.shortages_for is None) == (not self.lines):
            raise ValueError("give either shortages_for or lines, not both and not neither")
        return self


def _resolve_supplier(product: Product, name: str) -> int:
    name_l = name.strip().lower()
    for sp in product.suppliers:
        if sp.supplier.lower() == name_l or name_l in sp.supplier.lower():
            return sp.supplier_id
    options = ", ".join(sp.supplier for sp in product.suppliers) or "none"
    raise ToolError(f"{product.code} is not sold by '{name}'. Its suppliers: {options}.")


def draft_purchase_orders(ctx: ToolContext, args: DraftPurchaseOrdersInput) -> PurchaseProposal:
    data = ctx.data
    try:
        if args.shortages_for:
            product = resolve_product(data, args.shortages_for.product)
            if product.id not in data.boms:
                raise ToolError(f"{product.code} is purchased, not manufactured; order it with `lines` instead.")
            return proposal_for_shortages(
                data,
                product.id,
                args.shortages_for.quantity,
                count_incoming=args.shortages_for.count_incoming,
                currency=ctx.currency,
            )
        requests = []
        for line in args.lines or []:
            product = resolve_product(data, line.product)
            supplier_id = _resolve_supplier(product, line.supplier) if line.supplier else None
            requests.append(LineRequest(product_id=product.id, quantity=line.quantity, supplier_id=supplier_id))
        return build_proposal(data, requests, currency=ctx.currency, summary="Purchase order request from chat")
    except ProposalError as exc:
        raise ToolError(str(exc)) from None


TOOLS: list[Tool] = [
    Tool(
        "search_products",
        "Find products by code or name. Returns codes, stock figures and unit costs. "
        "Use this when the user names a product loosely.",
        SearchProductsInput,
        search_products,
    ),
    Tool(
        "get_stock_levels",
        "Current stock for specific products, or for all products with reorder rules: on hand, free "
        "(unreserved), incoming, and whether each is below its reorder minimum.",
        StockLevelsInput,
        get_stock_levels,
    ),
    Tool(
        "get_bom",
        "Bill of materials of a manufactured product: its components and quantities per unit, optionally "
        "several levels deep, plus the rolled-up unit cost.",
        BomInput,
        get_bom,
    ),
    Tool(
        "get_bom_shortages",
        "What-if plan for building a quantity of a manufactured product: short components with suppliers "
        "and lead times, sub-assemblies to build, estimated purchase cost, work-center load and lead time. "
        "Use for any 'can we build N', 'what are we short of' or 'what would it cost' question.",
        BomShortagesInput,
        get_bom_shortages,
    ),
    Tool(
        "get_manufacturing_order",
        "Details of one manufacturing order by its reference.",
        ManufacturingOrderInput,
        get_manufacturing_order,
    ),
    Tool(
        "list_manufacturing_orders",
        "Manufacturing orders, optionally filtered by state, with counts per state.",
        ManufacturingOrdersInput,
        list_manufacturing_orders,
    ),
    Tool(
        "draft_purchase_orders",
        "Prepare draft purchase orders for the user to review. This does NOT create anything: it returns a "
        "proposal that is shown to the user with Confirm and Reject buttons, and only the user's confirmation "
        "creates draft RFQs in the ERP. Use shortages_for to order what is short for a build, or lines for "
        "explicit components.",
        DraftPurchaseOrdersInput,
        draft_purchase_orders,
    ),
    Tool(
        "get_sales_summary",
        "Sales overview: open orders and their value, confirmed orders per week, top customers, and the "
        "list of open orders.",
        SalesSummaryInput,
        get_sales_summary,
    ),
]
TOOLS_BY_NAME = {t.name: t for t in TOOLS}


@dataclass
class ToolRunner:
    """Validates and executes tool calls for one assistant turn."""

    ctx: ToolContext
    tools: dict[str, Tool] = field(default_factory=lambda: TOOLS_BY_NAME)

    def run(self, name: str, raw_input: Any) -> ToolOutcome:
        tool = self.tools.get(name)
        if tool is None:
            return _error(f"Unknown tool '{name}'. Available tools: {', '.join(self.tools)}.", "unknown tool")
        if not isinstance(raw_input, dict):
            return _error("Tool arguments must be a JSON object.", "invalid arguments")
        try:
            args = tool.input_model.model_validate(raw_input)
        except ValidationError as exc:
            problems = "; ".join(
                f"{'.'.join(map(str, e['loc'])) or 'input'}: {e['msg']}" for e in exc.errors(include_url=False)
            )
            return _error(f"Invalid arguments for {name}: {problems}", "invalid arguments")
        try:
            result = tool.handler(self.ctx, args)
        except ToolError as exc:
            return _error(str(exc), str(exc)[:80])
        except BomError as exc:
            return _error(f"Planning failed: {exc}", "planning error")
        except OdooError:
            # Don't leak connection details to the model; the UI shows a generic failure.
            return _error("The ERP system could not be reached. Tell the user to try again shortly.", "ERP unavailable")
        if isinstance(result, PurchaseProposal):
            # The chat loop stores the proposal and replaces this content with
            # the proposal id; the model never sees a write it could claim happened.
            return ToolOutcome(ok=True, content="", summary="proposal ready", proposal=result)
        return ToolOutcome(ok=True, content=json.dumps(result, ensure_ascii=False, default=str), summary="ok")


def _error(message: str, summary: str) -> ToolOutcome:
    return ToolOutcome(ok=False, content=json.dumps({"error": message}, ensure_ascii=False), summary=summary)
