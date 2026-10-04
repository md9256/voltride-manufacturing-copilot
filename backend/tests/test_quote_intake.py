import json

import pytest

from app.ai.extraction import QUOTE_SCHEMA
from app.schemas.erp import PurchaseOrderRef, SupplierSummary
from app.schemas.intake import ExtractedQuote, LineCorrection, ReviewCorrections
from app.services.quote_intake import ReviewContext, amounts_match, build_review, match_product, review_to_proposal
from tests.factories import CHIP, CTL, PCB, data, mini_voltride, product

SUPPLIERS = [
    SupplierSummary(id=201, name="ChipCo", ref=None),
    SupplierSummary(id=202, name="BoardCo", ref=None),
    SupplierSummary(id=203, name="PanelCo", ref=None),
]


def quote(**overrides) -> ExtractedQuote:
    base = {
        "document_type": "quote",
        "supplier_name": "ChipCo",
        "quote_number": "Q-100",
        "quote_date": "2026-10-01",
        "currency": "HKD",
        "lines": [
            {
                "description": "CHIP microcontroller",
                "supplier_product_code": "CHIP",
                "quantity": 10,
                "unit_price": 60,
                "line_total": 600,
            },
            {
                "description": "Printed circuit board",
                "supplier_product_code": "PCB",
                "quantity": 2,
                "unit_price": 140,
                "line_total": 280,
            },
        ],
        "subtotal": 880,
        "tax": 0,
        "total": 880,
        "uncertain_fields": [],
    }
    base.update(overrides)
    return ExtractedQuote.model_validate(base)


def ctx(**overrides) -> ReviewContext:
    values = {
        "data": mini_voltride(),
        "suppliers": SUPPLIERS,
        "company_currency": "HKD",
        "existing_orders": [],
        "pending_quotes": [],
        "seen_file_before": False,
    }
    values.update(overrides)
    return ReviewContext(**values)


def review(q=None, c=None, corrections=None):
    return build_review("r1", "q.pdf", q or quote(), c or ctx(), corrections)


def errors(r):
    return [f.message for f in r.flags if f.severity == "error"] + [
        f.message for line in r.lines if line.include for f in line.flags if f.severity == "error"
    ]


def warnings(r):
    return [f.message for f in r.flags if f.severity == "warning"] + [
        f.message for line in r.lines for f in line.flags if f.severity == "warning"
    ]


def test_clean_quote_can_be_proposed():
    r = review()
    assert errors(r) == []
    assert r.can_propose
    assert (r.supplier.id, r.supplier_match) == (201, "exact")
    assert [(line.product.id, line.match) for line in r.lines] == [(CHIP, "code"), (PCB, "code")]
    assert r.computed_total == 880


def test_line_arithmetic_error_blocks():
    q = quote(
        lines=[
            {"description": "CHIP", "supplier_product_code": None, "quantity": 10, "unit_price": 60, "line_total": 650}
        ],
        subtotal=650,
        total=650,
    )
    r = review(q)
    assert not r.can_propose
    assert any("10 x 60.00 = 600.00, but the line says 650.00" in e for e in errors(r))


def test_document_totals_must_add_up():
    r = review(quote(subtotal=900, total=900))
    assert any("Lines add up to 880.00" in e for e in errors(r))
    r = review(quote(tax=88, total=900))
    assert any("Subtotal plus tax is 968.00" in e for e in errors(r))


def test_correcting_a_misread_quantity_fixes_the_arithmetic():
    q = quote(
        lines=[
            {
                "description": "CHIP",
                "supplier_product_code": "CHIP",
                "quantity": 80,
                "unit_price": 60,
                "line_total": 600,
            }
        ],
        subtotal=600,
        total=600,
    )
    assert not review(q).can_propose
    fixed = review(q, corrections=ReviewCorrections(lines={0: LineCorrection(quantity=10)}))
    assert fixed.can_propose
    assert fixed.lines[0].quantity == 10


def test_fuzzy_supplier_name_is_a_warning():
    r = review(quote(supplier_name="ChipCo Electronics Ltd."))
    assert r.supplier_match == "fuzzy"
    assert any("matched to ChipCo" in w for w in warnings(r))
    assert r.can_propose


def test_unknown_supplier_blocks_until_chosen():
    r = review(quote(supplier_name="Totally Different Trading"))
    assert r.supplier is None and not r.can_propose
    chosen = review(quote(supplier_name="Totally Different Trading"), corrections=ReviewCorrections(supplier_id=201))
    assert chosen.supplier_match == "manual" and chosen.can_propose


def test_unknown_product_blocks_until_matched_or_excluded():
    q = quote(
        lines=[
            {
                "description": "CHIP",
                "supplier_product_code": "CHIP",
                "quantity": 10,
                "unit_price": 60,
                "line_total": 600,
            },
            {
                "description": "Flux capacitor",
                "supplier_product_code": "FX-1",
                "quantity": 1,
                "unit_price": 5,
                "line_total": 5,
            },
        ],
        subtotal=605,
        total=605,
    )
    r = review(q)
    assert r.lines[1].match == "none" and not r.can_propose
    excluded = review(q, corrections=ReviewCorrections(lines={1: LineCorrection(include=False)}))
    assert excluded.can_propose
    assert excluded.computed_total == 600  # excluded line not ordered...
    assert errors(excluded) == []  # ...and document totals still checked on all printed lines


def test_manufactured_product_cannot_be_purchased():
    r = review(corrections=ReviewCorrections(lines={1: LineCorrection(product_id=CTL)}))
    assert any("manufactured in-house" in e for e in errors(r))


def test_product_not_on_supplier_price_list_and_price_deviation_warn():
    q = quote(
        lines=[
            {"description": "LCD", "supplier_product_code": "LCD", "quantity": 1, "unit_price": 200, "line_total": 200}
        ],
        subtotal=200,
        total=200,
    )
    r = review(q)
    assert any("not on ChipCo's price list" in w for w in warnings(r))
    r = review(quote(supplier_name="PanelCo", lines=q.model_dump()["lines"], subtotal=200, total=200))
    assert r.lines[0].agreed_price == 160
    assert any("+25% vs the agreed 160.00" in w for w in warnings(r))
    assert r.can_propose  # warnings don't block


def test_currency_mismatch_blocks():
    assert any("Quote is in USD" in e for e in errors(review(quote(currency="USD"))))


def test_duplicate_of_existing_purchase_order_blocks():
    existing = PurchaseOrderRef(
        id=1,
        name="P00001",
        supplier_id=201,
        supplier="ChipCo",
        partner_ref="q-100",
        origin=None,
        state="purchase",
        amount_total=880,
    )
    r = review(c=ctx(existing_orders=[existing]))
    assert any("already entered as P00001" in e for e in errors(r))
    # Same quote number from a different supplier is not a duplicate.
    other = existing.model_copy(update={"supplier_id": 202})
    assert review(c=ctx(existing_orders=[other])).can_propose


def test_pending_proposal_for_same_quote_blocks_and_same_file_warns():
    r = review(c=ctx(pending_quotes=[(201, "Q-100")], seen_file_before=True))
    assert any("already waiting for confirmation" in e for e in errors(r))
    assert any("uploaded before" in w for w in warnings(r))


def test_model_uncertainty_is_surfaced():
    r = review(quote(uncertain_fields=["total", "lines[1].unit_price"]))
    fields = [f.field for f in r.flags] + [f.field for line in r.lines for f in line.flags]
    assert "total" in fields and "lines[1].unit_price" in fields


def test_not_a_quote_blocks():
    assert any("does not look like" in e for e in errors(review(quote(document_type="other"))))


def test_review_to_proposal():
    r = review()
    p = review_to_proposal(r, file_sha256="abc")
    [order] = p.orders
    assert (order.supplier_id, order.partner_ref, order.total) == (201, "Q-100", 880)
    assert [(line.code, line.quantity, line.unit_price) for line in order.lines] == [("CHIP", 10, 60), ("PCB", 2, 140)]
    assert p.quote.file_sha256 == "abc"


def test_review_with_errors_cannot_become_a_proposal():
    with pytest.raises(ValueError):
        review_to_proposal(review(quote(currency="USD")), file_sha256="x")


def test_match_product_by_code_and_by_reordered_name():
    d = data(
        [
            product(5, "CHP-MCU").model_copy(update={"name": "MCU chip STM32G4"}),
            product(6, "CHP-MOS").model_copy(update={"name": "MOSFET power stage pack"}),
            product(9, "LCD-35").model_copy(update={"name": "3.5in colour LCD panel"}),
        ],
        [],
    )
    assert match_product("Display, item LCD-35", None, d)[:2][1] == "code"
    found, how, _ = match_product("STM32G4 MCU chip", None, d)  # same words, different order
    assert (found.id, how) == (5, "name")
    found, how, _ = match_product("Regenerative brake controller", "RBC-9", d)
    assert (found, how) == (None, "none")  # no confident wrong guess


@pytest.mark.parametrize(
    ("a", "b", "same"), [(100, 100.01, True), (100, 100.2, False), (100000, 100030, True), (100000, 100400, False)]
)
def test_amounts_match_tolerance(a, b, same):
    assert amounts_match(a, b) is same


def test_llm_schema_is_closed_and_self_contained():
    text = json.dumps(QUOTE_SCHEMA)
    assert "$ref" not in text and "$defs" not in text
    assert QUOTE_SCHEMA["additionalProperties"] is False
    assert set(QUOTE_SCHEMA["required"]) == set(QUOTE_SCHEMA["properties"])
    line = QUOTE_SCHEMA["properties"]["lines"]["items"]
    assert line["additionalProperties"] is False and set(line["required"]) == set(line["properties"])
