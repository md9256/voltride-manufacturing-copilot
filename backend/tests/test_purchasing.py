import pytest

from app.services.purchasing import (
    MAX_PROPOSAL_TOTAL,
    LineRequest,
    ProposalError,
    build_proposal,
    proposal_for_shortages,
    revalidate,
)
from tests.factories import BOX, CHIP, CTL, KIT, LCD, PCB, data, mini_voltride, product, supplier

VENDORS = {201, 202, 203, 204}


def proposal(requests, d=None):
    return build_proposal(d or mini_voltride(), requests, currency="HKD", summary="test")


def test_groups_lines_by_supplier_at_price_list_prices():
    p = proposal([LineRequest(CHIP, 10), LineRequest(PCB, 2), LineRequest(BOX, 5)])
    by_supplier = {o.supplier: o for o in p.orders}
    assert set(by_supplier) == {"ChipCo", "BoardCo", "BoxCo"}
    assert by_supplier["ChipCo"].lines[0].unit_price == 60
    assert by_supplier["ChipCo"].total == 600
    assert p.total == 600 + 280 + 100
    assert [o.supplier for o in p.orders] == ["ChipCo", "BoardCo", "BoxCo"]  # largest first


def test_same_product_requested_twice_is_merged():
    p = proposal([LineRequest(CHIP, 4), LineRequest(CHIP, 6)])
    [order] = p.orders
    assert [(line.code, line.quantity) for line in order.lines] == [("CHIP", 10)]


def test_supplier_minimum_rounds_up_with_warning():
    d = mini_voltride(CHIP=product(CHIP, "CHIP", suppliers=[supplier("ChipCo", 60, min_qty=50, sid=201)]))
    p = proposal([LineRequest(CHIP, 7)], d)
    assert p.orders[0].lines[0].quantity == 50
    assert p.warnings == ["CHIP: rounded up to supplier minimum of 50"]


def test_explicit_supplier_must_sell_the_product():
    with pytest.raises(ProposalError, match="does not sell CHIP"):
        proposal([LineRequest(CHIP, 1, supplier_id=203)])


@pytest.mark.parametrize(
    ("requests", "message"),
    [
        ([LineRequest(CTL, 1)], "manufactured in-house"),
        ([LineRequest(CHIP, 0)], "must be positive"),
        ([], "Nothing to order"),
    ],
)
def test_invalid_requests_are_refused(requests, message):
    with pytest.raises(ProposalError, match=message):
        proposal(requests)


def test_product_without_supplier_cannot_be_ordered():
    d = data([product(1, "ORPHAN")], [])
    with pytest.raises(ProposalError, match="no supplier"):
        build_proposal(d, [LineRequest(1, 1)], currency="HKD", summary="x")


def test_total_over_sanity_limit_is_refused():
    with pytest.raises(ProposalError, match="exceeds"):
        proposal([LineRequest(CHIP, MAX_PROPOSAL_TOTAL / 60 + 1)])


def test_shortage_proposal_orders_exactly_the_planner_shortage():
    p = proposal_for_shortages(mini_voltride(), KIT, 5, count_incoming=False, currency="HKD")
    # 10 chips needed, 3 free -> 7 short; everything else in stock.
    [order] = p.orders
    assert [(line.code, line.quantity) for line in order.lines] == [("CHIP", 7)]
    assert "5 x KIT" in p.summary


def test_shortage_proposal_when_nothing_is_short():
    with pytest.raises(ProposalError, match="Nothing is short"):
        proposal_for_shortages(mini_voltride(), KIT, 1, count_incoming=False, currency="HKD")


def test_revalidate_accepts_untouched_proposal():
    p = proposal([LineRequest(CHIP, 10), LineRequest(LCD, 1)])
    assert revalidate(p, mini_voltride(), VENDORS) == []


def test_revalidate_catches_tampered_totals_and_vanished_vendor():
    p = proposal([LineRequest(CHIP, 10)])
    p.orders[0].lines[0].quantity = 1000  # subtotal no longer matches
    problems = revalidate(p, mini_voltride(), VENDORS - {201})
    assert any("no longer exists as a vendor" in x for x in problems)
    assert any("subtotal does not match" in x for x in problems)


def test_revalidate_catches_product_that_became_manufactured():
    p = proposal([LineRequest(CHIP, 1)])
    d = mini_voltride()
    d.boms[CHIP] = d.boms[CTL]  # CHIP now has a BOM
    assert any("no longer a purchased" in x for x in revalidate(p, d, VENDORS))
