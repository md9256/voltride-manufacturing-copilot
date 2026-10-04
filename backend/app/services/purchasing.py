"""Purchase proposals: build them, and re-check them before they are written.

Pure functions over ERP records (no Odoo, no LLM, no database), so the rules
that decide what may be ordered are unit-tested directly.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from app.schemas.actions import ProposalLine, ProposalOrder, PurchaseProposal
from app.services.bom import ManufacturingData
from app.services.planner import choose_supplier, plan

# Sanity limits on a single proposal. A proposal over these is almost
# certainly a misunderstanding (e.g. units confused with thousands) and is
# refused rather than shown with a Confirm button.
MAX_PROPOSAL_TOTAL = 1_000_000.0  # company currency
MAX_LINES = 50


class ProposalError(ValueError):
    """The request cannot be turned into a valid proposal; the message says why."""


@dataclass(frozen=True)
class LineRequest:
    product_id: int
    quantity: float
    supplier_id: int | None = None  # None: choose the best supplier


def build_proposal(
    data: ManufacturingData, requests: list[LineRequest], *, currency: str, summary: str
) -> PurchaseProposal:
    """Turn requested quantities into per-supplier draft orders at price-list prices."""
    if not requests:
        raise ProposalError("Nothing to order.")
    merged: dict[tuple[int, int], float] = defaultdict(float)
    notes: dict[tuple[int, int], str] = {}
    leads: dict[int, int] = {}
    for req in requests:
        product = data.product(req.product_id)
        label = product.code or product.name
        if data.kind(product.id) != "purchased":
            raise ProposalError(f"{label} is manufactured in-house, not purchased.")
        if req.quantity <= 0:
            raise ProposalError(f"Quantity for {label} must be positive.")
        if req.supplier_id is not None:
            matches = [s for s in product.suppliers if s.supplier_id == req.supplier_id]
            if not matches:
                vendors = ", ".join(s.supplier for s in product.suppliers) or "none"
                raise ProposalError(f"That supplier does not sell {label}. Its suppliers: {vendors}.")
            chosen, qty, note = choose_supplier(matches, req.quantity)
        else:
            chosen, qty, note = choose_supplier(product.suppliers, req.quantity)
        if chosen is None:
            raise ProposalError(f"{label} has no supplier configured, so it cannot be ordered.")
        key = (chosen.supplier_id, product.id)
        merged[key] += qty
        if note:
            notes[key] = note
        leads[chosen.supplier_id] = max(leads.get(chosen.supplier_id, 0), chosen.lead_days)

    by_supplier: dict[int, list[ProposalLine]] = defaultdict(list)
    supplier_names: dict[int, str] = {}
    for (supplier_id, product_id), qty in merged.items():
        product = data.products[product_id]
        price_line = next(s for s in product.suppliers if s.supplier_id == supplier_id)
        supplier_names[supplier_id] = price_line.supplier
        by_supplier[supplier_id].append(
            ProposalLine(
                product_id=product_id,
                code=product.code,
                name=product.name,
                quantity=round(qty, 4),
                unit_price=price_line.price,
                subtotal=round(qty * price_line.price, 2),
                note=notes.get((supplier_id, product_id)),
            )
        )
    orders = [
        ProposalOrder(
            supplier_id=sid,
            supplier=supplier_names[sid],
            lead_days=leads.get(sid),
            lines=sorted(lines, key=lambda line: line.code or line.name),
            total=round(sum(line.subtotal for line in lines), 2),
        )
        for sid, lines in by_supplier.items()
    ]
    orders.sort(key=lambda o: -o.total)
    proposal = PurchaseProposal(
        summary=summary,
        currency=currency,
        orders=orders,
        total=round(sum(o.total for o in orders), 2),
        warnings=[f"{line.code}: {line.note}" for o in orders for line in o.lines if line.note],
    )
    check_limits(proposal)
    return proposal


def proposal_for_shortages(
    data: ManufacturingData, product_id: int, quantity: float, *, count_incoming: bool, currency: str
) -> PurchaseProposal:
    """Order exactly what the planner says is short for building `quantity` units."""
    result = plan(data, product_id, quantity, count_incoming=count_incoming)
    requests = [
        LineRequest(product_id=r.product_id, quantity=r.shortage) for r in result.requirements if r.shortage > 0
    ]
    product = data.product(product_id)
    if not requests:
        raise ProposalError(
            f"Nothing is short for building {quantity:g} x {product.code}"
            + (" (counting incoming receipts)." if count_incoming else ".")
        )
    return build_proposal(
        data,
        requests,
        currency=currency,
        summary=f"Order shortages for building {quantity:g} x {product.code}"
        + ("" if count_incoming else " (ignoring incoming receipts)"),
    )


def check_limits(proposal: PurchaseProposal) -> None:
    line_count = sum(len(o.lines) for o in proposal.orders)
    if line_count > MAX_LINES:
        raise ProposalError(f"Too many lines ({line_count}); the limit is {MAX_LINES}.")
    if proposal.total > MAX_PROPOSAL_TOTAL:
        raise ProposalError(
            f"Total {proposal.total:,.2f} {proposal.currency} exceeds the {MAX_PROPOSAL_TOTAL:,.0f} limit "
            "for a single proposal."
        )


def revalidate(proposal: PurchaseProposal, data: ManufacturingData, vendor_ids: set[int]) -> list[str]:
    """Re-check a stored proposal against current ERP data just before writing.

    Minutes may have passed since it was proposed, and the stored payload is
    never trusted blindly. Returns problems; an empty list means safe to write.
    """
    problems: list[str] = []
    try:
        check_limits(proposal)
    except ProposalError as exc:
        problems.append(str(exc))
    for order in proposal.orders:
        if order.supplier_id not in vendor_ids:
            problems.append(f"Supplier {order.supplier} no longer exists as a vendor.")
        for line in order.lines:
            product = data.products.get(line.product_id)
            if product is None:
                problems.append(f"Product {line.code or line.product_id} no longer exists.")
            elif data.kind(product.id) != "purchased":
                problems.append(f"{product.code} is no longer a purchased product.")
            if abs(line.quantity * line.unit_price - line.subtotal) > 0.01:
                problems.append(f"Line {line.code}: subtotal does not match quantity x price.")
        if abs(sum(line.subtotal for line in order.lines) - order.total) > 0.01:
            problems.append(f"Order for {order.supplier}: total does not match its lines.")
    if abs(sum(o.total for o in proposal.orders) - proposal.total) > 0.01:
        problems.append("Proposal total does not match its orders.")
    return problems
