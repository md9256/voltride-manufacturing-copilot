"""Supplier quote review: deterministic checks on what the LLM extracted.

The LLM only reads the document. Every decision about whether the result can
become a purchase order is made here, in plain code: arithmetic, supplier and
product matching, price sanity, currency and duplicates. Problems are flagged
as errors (block creating the order) or warnings (shown, not blocking). The
user can correct matches and figures; corrected values are re-checked the
same way.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass

from app.schemas.actions import ProposalLine, ProposalOrder, PurchaseProposal, QuoteSource
from app.schemas.erp import Product, PurchaseOrderRef, SupplierSummary
from app.schemas.intake import (
    ExtractedQuote,
    Flag,
    LineReview,
    ProductOption,
    QuoteReviewView,
    ReviewCorrections,
)
from app.services.bom import ManufacturingData
from app.services.purchasing import check_limits

PRICE_TOLERANCE = 0.10  # warn when a quoted price is >10% from the agreed price list
FUZZY_SUPPLIER = 0.75
FUZZY_PRODUCT = 0.6


def amounts_match(a: float, b: float) -> bool:
    """Equal within rounding: 2 cents, or 0.05% for large amounts (per-unit
    prices with more decimals than printed can drift a little on big quantities)."""
    return abs(a - b) <= max(0.02, 0.0005 * max(abs(a), abs(b)))


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _similarity(a: str, b: str) -> float:
    """Best of character similarity and word overlap.

    Word overlap (Dice coefficient) handles reordered names such as
    "STM32G4 MCU chip" vs "MCU chip STM32G4", which character similarity
    scores poorly.
    """
    na, nb = _norm(a), _norm(b)
    chars = difflib.SequenceMatcher(None, na, nb).ratio()
    wa, wb = set(na.split()), set(nb.split())
    words = 2 * len(wa & wb) / (len(wa) + len(wb)) if wa and wb else 0.0
    return max(chars, words)


@dataclass
class ReviewContext:
    """Everything the checks need from the ERP and the app database."""

    data: ManufacturingData
    suppliers: list[SupplierSummary]
    company_currency: str
    existing_orders: list[PurchaseOrderRef]  # purchase orders (any supplier) carrying this quote number
    pending_quotes: list[tuple[int, str]]  # (supplier id, quote number) of other pending proposals
    seen_file_before: bool  # the same PDF (by hash) was uploaded before


def match_supplier(name: str | None, suppliers: list[SupplierSummary]) -> tuple[SupplierSummary | None, str, list]:
    if not name:
        return None, "none", []
    ranked = sorted(suppliers, key=lambda s: -_similarity(name, s.name))
    for s in suppliers:
        if _norm(s.name) == _norm(name):
            return s, "exact", ranked[:5]
    best = ranked[0] if ranked else None
    if best and (_similarity(name, best.name) >= FUZZY_SUPPLIER or _norm(best.name) in _norm(name)):
        return best, "fuzzy", ranked[:5]
    return None, "none", ranked[:5]


def match_product(line_text: str, code: str | None, data: ManufacturingData) -> tuple[Product | None, str, list]:
    products = list(data.products.values())
    haystack = f" {_norm(line_text)} {_norm(code or '')} "
    by_code = [p for p in products if p.code and f" {_norm(p.code)} " in haystack]
    ranked = sorted(products, key=lambda p: -_similarity(line_text, p.name))
    if len(by_code) == 1:
        return by_code[0], "code", ranked[:5]
    best = ranked[0] if ranked else None
    if best and _similarity(line_text, best.name) >= FUZZY_PRODUCT:
        runner_up = ranked[1] if len(ranked) > 1 else None
        if not runner_up or _similarity(line_text, best.name) - _similarity(line_text, runner_up.name) > 0.05:
            return best, "name", ranked[:5]
    return None, "none", ranked[:5]


def _option(p) -> ProductOption:
    return ProductOption(id=p.id, code=getattr(p, "code", None), name=p.name)


def build_review(
    review_id: str,
    filename: str,
    extracted: ExtractedQuote,
    ctx: ReviewContext,
    corrections: ReviewCorrections | None = None,
) -> QuoteReviewView:
    corrections = corrections or ReviewCorrections()
    data = ctx.data
    flags: list[Flag] = []
    uncertain = set(extracted.uncertain_fields)

    def unsure(path: str) -> list[Flag]:
        if path in uncertain:
            return [Flag(severity="warning", field=path, message="The model was unsure reading this value; check it.")]
        return []

    if extracted.document_type == "other":
        flags.append(
            Flag(
                severity="error", field="document_type", message="This does not look like a supplier quote or invoice."
            )
        )

    # Supplier
    supplier, supplier_match, candidates = match_supplier(extracted.supplier_name, ctx.suppliers)
    if corrections.supplier_id is not None:
        supplier = next((s for s in ctx.suppliers if s.id == corrections.supplier_id), None)
        supplier_match = "manual" if supplier else "none"
    if supplier is None:
        flags.append(
            Flag(
                severity="error",
                field="supplier",
                message=f"No vendor matches '{extracted.supplier_name or '?'}'. Choose one.",
            )
        )
    elif supplier_match == "fuzzy":
        flags.append(
            Flag(
                severity="warning",
                field="supplier",
                message=f"'{extracted.supplier_name}' matched to {supplier.name}; confirm this is right.",
            )
        )
    flags += unsure("supplier_name")

    # Header fields
    if not extracted.quote_number:
        flags.append(
            Flag(
                severity="warning",
                field="quote_number",
                message="No quote number found, so duplicates cannot be detected.",
            )
        )
    flags += unsure("quote_number")
    if not extracted.currency:
        flags.append(
            Flag(severity="warning", field="currency", message=f"No currency found; assuming {ctx.company_currency}.")
        )
    elif extracted.currency.upper() != ctx.company_currency.upper():
        flags.append(
            Flag(
                severity="error",
                field="currency",
                message=f"Quote is in {extracted.currency}; purchase orders here are in {ctx.company_currency}.",
            )
        )

    # Duplicates: the same quote number from the same supplier
    number = (extracted.quote_number or "").strip().lower()
    if supplier and number:
        dupes = [po for po in ctx.existing_orders if po.supplier_id == supplier.id]
        if dupes:
            names = ", ".join(po.name for po in dupes)
            flags.append(
                Flag(
                    severity="error",
                    field="quote_number",
                    message=f"Quote {extracted.quote_number} is already entered as {names}.",
                )
            )
        if any(sid == supplier.id and q.strip().lower() == number for sid, q in ctx.pending_quotes):
            flags.append(
                Flag(
                    severity="error",
                    field="quote_number",
                    message="A proposal for this quote is already waiting for confirmation.",
                )
            )
    if ctx.seen_file_before:
        flags.append(Flag(severity="warning", field="file", message="This exact file was uploaded before."))

    # Lines
    lines: list[LineReview] = []
    for i, ext in enumerate(extracted.lines):
        fix = corrections.lines.get(i)
        qty = fix.quantity if fix and fix.quantity is not None else ext.quantity
        price = fix.unit_price if fix and fix.unit_price is not None else ext.unit_price
        line_total = fix.line_total if fix and fix.line_total is not None else ext.line_total
        include = fix.include if fix and fix.include is not None else True
        line_flags: list[Flag] = []
        path = f"lines[{i}]"

        product, match, cands = match_product(ext.description, ext.supplier_product_code, data)
        if fix and fix.product_id is not None:
            product = data.products.get(fix.product_id)
            match = "manual" if product else "none"

        agreed = None
        if include:
            if product is None:
                line_flags.append(
                    Flag(
                        severity="error",
                        field=f"{path}.product",
                        message="No matching product. Choose one or exclude the line.",
                    )
                )
            else:
                if match == "name":
                    line_flags.append(
                        Flag(
                            severity="warning",
                            field=f"{path}.product",
                            message=f"Matched by name to {product.code}; confirm.",
                        )
                    )
                if data.kind(product.id) != "purchased":
                    line_flags.append(
                        Flag(
                            severity="error",
                            field=f"{path}.product",
                            message=f"{product.code} is manufactured in-house, not purchased.",
                        )
                    )
                if supplier:
                    sells = [s for s in product.suppliers if s.supplier_id == supplier.id]
                    if sells:
                        agreed = sells[0].price
                    else:
                        line_flags.append(
                            Flag(
                                severity="warning",
                                field=f"{path}.product",
                                message=f"{product.code} is not on {supplier.name}'s price list.",
                            )
                        )
            if qty is None or qty <= 0:
                line_flags.append(
                    Flag(severity="error", field=f"{path}.quantity", message="Quantity missing or not positive.")
                )
            if price is None or price < 0:
                line_flags.append(Flag(severity="error", field=f"{path}.unit_price", message="Unit price missing."))
            if qty and price is not None and line_total is not None and not amounts_match(qty * price, line_total):
                line_flags.append(
                    Flag(
                        severity="error",
                        field=f"{path}.line_total",
                        message=f"{qty:g} x {price:,.2f} = {qty * price:,.2f}, but the line says {line_total:,.2f}.",
                    )
                )
            if agreed and price is not None and agreed > 0 and abs(price - agreed) / agreed > PRICE_TOLERANCE:
                line_flags.append(
                    Flag(
                        severity="warning",
                        field=f"{path}.unit_price",
                        message=f"{price:,.2f} is {100 * (price - agreed) / agreed:+.0f}% vs the agreed {agreed:,.2f}.",
                    )
                )
            for field in ("quantity", "unit_price", "line_total", "description"):
                line_flags += unsure(f"{path}.{field}")

        lines.append(
            LineReview(
                index=i,
                description=ext.description,
                supplier_product_code=ext.supplier_product_code,
                quantity=qty,
                unit_price=price,
                line_total=line_total,
                include=include,
                product=_option(product) if product else None,
                match=match,
                candidates=[_option(p) for p in cands],
                agreed_price=agreed,
                flags=line_flags,
            )
        )

    # Document totals: do the printed lines add up to the printed totals?
    line_amounts = [
        line.line_total if line.line_total is not None else (line.quantity or 0) * (line.unit_price or 0)
        for line in lines
    ]
    lines_sum = round(sum(line_amounts), 2)
    if extracted.subtotal is not None and not amounts_match(lines_sum, extracted.subtotal):
        flags.append(
            Flag(
                severity="error",
                field="subtotal",
                message=f"Lines add up to {lines_sum:,.2f}, but the subtotal says {extracted.subtotal:,.2f}.",
            )
        )
    if extracted.total is not None:
        expected = (extracted.subtotal if extracted.subtotal is not None else lines_sum) + (extracted.tax or 0)
        if not amounts_match(expected, extracted.total):
            flags.append(
                Flag(
                    severity="error",
                    field="total",
                    message=f"Subtotal plus tax is {expected:,.2f}, but the total says {extracted.total:,.2f}.",
                )
            )
    for field in ("subtotal", "tax", "total"):
        flags += unsure(field)
    if extracted.tax:
        flags.append(
            Flag(
                severity="warning",
                field="tax",
                message="The quote includes tax; the draft order uses pre-tax unit prices.",
            )
        )

    included = [line for line in lines if line.include]
    if not included:
        flags.append(Flag(severity="error", field="lines", message="No lines are included."))
    computed_total = round(sum((line.quantity or 0) * (line.unit_price or 0) for line in included), 2)
    has_error = any(f.severity == "error" for f in flags) or any(
        f.severity == "error" for line in included for f in line.flags
    )
    return QuoteReviewView(
        id=review_id,
        filename=filename,
        document_type=extracted.document_type,
        supplier_name=extracted.supplier_name,
        supplier=ProductOption(id=supplier.id, code=None, name=supplier.name) if supplier else None,
        supplier_match=supplier_match,
        supplier_candidates=[ProductOption(id=s.id, code=None, name=s.name) for s in candidates],
        quote_number=extracted.quote_number,
        quote_date=extracted.quote_date,
        currency=extracted.currency,
        company_currency=ctx.company_currency,
        lines=lines,
        subtotal=extracted.subtotal,
        tax=extracted.tax,
        total=extracted.total,
        computed_total=computed_total,
        flags=flags,
        can_propose=not has_error,
    )


def review_to_proposal(review: QuoteReviewView, *, file_sha256: str) -> PurchaseProposal:
    """Turn an error-free review into a proposal (one draft PO for the quoting supplier)."""
    if not review.can_propose or review.supplier is None:
        raise ValueError("The review still has errors.")
    lines = [
        ProposalLine(
            product_id=line.product.id,
            code=line.product.code,
            name=line.product.name,
            quantity=line.quantity,
            unit_price=line.unit_price,
            subtotal=round(line.quantity * line.unit_price, 2),
        )
        for line in review.lines
        if line.include and line.product and line.quantity and line.unit_price is not None
    ]
    total = round(sum(line.subtotal for line in lines), 2)
    warnings = [f.message for f in review.flags if f.severity == "warning"] + [
        f"Line {line.index + 1}: {f.message}" for line in review.lines if line.include for f in line.flags
    ]
    proposal = PurchaseProposal(
        summary=f"Supplier quote {review.quote_number or '(no number)'} from {review.supplier.name}",
        currency=review.company_currency,
        orders=[
            ProposalOrder(
                supplier_id=review.supplier.id,
                supplier=review.supplier.name,
                partner_ref=review.quote_number,
                lines=lines,
                total=total,
            )
        ],
        total=total,
        warnings=warnings,
        quote=QuoteSource(
            review_id=review.id, quote_number=review.quote_number, filename=review.filename, file_sha256=file_sha256
        ),
    )
    check_limits(proposal)
    return proposal
