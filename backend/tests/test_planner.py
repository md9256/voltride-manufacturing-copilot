import pytest

from app.services.planner import choose_supplier, plan
from tests.factories import (
    CHIP,
    CTL,
    DSP,
    KIT,
    LCD,
    bom,
    data,
    mini_voltride,
    product,
    supplier,
    work_center,
)


def req(result, pid):
    return next(r for r in result.requirements if r.product_id == pid)


def test_shared_component_is_netted_once_across_branches():
    # 2 kits need 2 chips via controllers + 2 via displays = 4. Free stock is 3.
    # Netting each branch separately would wrongly report no shortage (3 >= 2 twice).
    result = plan(mini_voltride(), KIT, 2, count_incoming=False)
    chip = req(result, CHIP)
    assert (chip.gross_qty, chip.from_stock, chip.shortage) == (4, 3, 1)
    assert chip.level == 2


def test_root_is_built_in_full_even_with_stock():
    d = mini_voltride(KIT=product(KIT, "KIT", free=50))
    assert req(plan(d, KIT, 2), KIT).to_build == 2


def test_subassembly_stock_is_used_before_building():
    # 3 controllers in stock: building 5 kits needs only 2 more controllers,
    # so the controller branch asks for 2 chips, the display branch for 5.
    d = mini_voltride(CTL=product(CTL, "CTL", free=3))
    result = plan(d, KIT, 5, count_incoming=False)
    assert (req(result, CTL).from_stock, req(result, CTL).to_build) == (3, 2)
    assert req(result, CHIP).gross_qty == 7


def test_free_stock_not_on_hand_is_used():
    d = mini_voltride(CHIP=product(CHIP, "CHIP", free=0, on_hand=50, suppliers=[supplier("ChipCo", 60)]))
    assert req(plan(d, KIT, 1, count_incoming=False), CHIP).shortage == 2


def test_incoming_receipts_cover_shortage_when_counted():
    d = mini_voltride(CHIP=product(CHIP, "CHIP", free=3, incoming=10, suppliers=[supplier("ChipCo", 60)]))
    counted = req(plan(d, KIT, 2, count_incoming=True), CHIP)
    ignored = req(plan(d, KIT, 2, count_incoming=False), CHIP)
    assert (counted.covered_by_incoming, counted.shortage, counted.status) == (1, 0, "incoming")
    assert (ignored.covered_by_incoming, ignored.shortage, ignored.status) == (0, 1, "short")


def test_short_status_propagates_to_parents():
    result = plan(mini_voltride(), KIT, 2, count_incoming=False)
    status = {r.product_id: r.status for r in result.requirements}
    assert status[CHIP] == "short"
    assert status[CTL] == status[DSP] == status[KIT] == "short"
    assert status[LCD] == "ok"


def test_buildable_subassembly_status():
    result = plan(mini_voltride(), KIT, 1, count_incoming=False)  # 2 chips needed, 3 free
    assert {r.product_id: r.status for r in result.requirements}[CTL] == "build"
    assert result.short_count == 0
    assert result.purchases == []


def test_kits_are_never_taken_from_stock():
    d = data(
        [product(1, "A"), product(2, "PH", free=99), product(3, "C", free=0, suppliers=[supplier("S", 1)])],
        [bom(1, 1, {2: 1}), bom(2, 2, {3: 2}, type="phantom")],
    )
    result = plan(d, 1, 3, count_incoming=False)
    assert req(result, 2).from_stock == 0
    assert req(result, 3).shortage == 6


def test_purchase_list_groups_by_supplier_with_cost():
    result = plan(mini_voltride(), KIT, 5, count_incoming=False)  # 10 chips needed, 3 free
    [group] = result.purchases
    assert group.supplier == "ChipCo"
    assert (group.lines[0].order_qty, group.lines[0].total) == (7, 420)
    assert result.purchase_total == 420


def test_supplier_choice_cheapest_eligible():
    options = [supplier("Bulk", 5, min_qty=100), supplier("Small", 8, min_qty=1), supplier("Mid", 7, min_qty=10)]
    chosen, qty, note = choose_supplier(options, 20)
    assert (chosen.supplier, qty, note) == ("Mid", 20, None)


def test_supplier_minimum_rounds_order_up():
    chosen, qty, note = choose_supplier([supplier("Bulk", 5, min_qty=100)], 20)
    assert (chosen.supplier, qty) == ("Bulk", 100)
    assert "minimum" in note


def test_no_supplier_prices_at_standard_cost():
    d = data([product(1, "A"), product(2, "B", cost=9)], [bom(1, 1, {2: 1})])
    [group] = plan(d, 1, 4).purchases
    assert group.supplier is None
    assert group.lines[0].total == 36
    assert "no supplier" in group.lines[0].note


def test_material_bottlenecks_sorted_by_lead_time():
    d = mini_voltride(LCD=product(LCD, "LCD", free=0, suppliers=[supplier("PanelCo", 160, lead_days=21)]))
    result = plan(d, KIT, 5, count_incoming=False)
    assert [m.code for m in result.material_bottlenecks] == ["CHIP", "LCD"]  # 35 days before 21


def test_capacity_load_and_bottleneck():
    result = plan(mini_voltride(), KIT, 10, count_incoming=False)
    load = {c.code: c.hours for c in result.capacity}
    # ASM: kit 30 min + controller 12 min, per kit. TST: controller 20 + display 6.
    assert load == {"ASM": pytest.approx(7.0), "TST": pytest.approx(26 * 10 / 60, abs=0.05)}
    assert result.capacity_bottleneck.code == "ASM"


def test_capacity_respects_efficiency():
    d = data(
        [product(1, "A")],
        [bom(1, 1, {}, ops=[(5, 60)])],
        [work_center(5, "W", efficiency=0.5, hours_per_day=4)],
    )
    [load] = plan(d, 1, 2).capacity
    assert (load.hours, load.days) == (4, 1)


def test_estimated_days_follow_critical_path():
    # Chip short (35 days lead) -> controller (12+20 min) -> kit (30 min), 1 kit, 8 h days.
    d = mini_voltride(CHIP=product(CHIP, "CHIP", free=0, suppliers=[supplier("ChipCo", 60, lead_days=35)]))
    result = plan(d, KIT, 1, count_incoming=False)
    assert result.estimated_days == pytest.approx(35 + (32 + 30) / 60 / 8, abs=0.1)


def test_no_work_when_everything_in_stock():
    d = mini_voltride(CHIP=product(CHIP, "CHIP", free=100))
    result = plan(d, KIT, 1)
    assert result.short_count == 0
    # Nothing to buy, but the kit and its sub-assemblies still need building.
    assert {c.code for c in result.capacity} == {"ASM", "TST"}


def test_capacity_ranking_uses_unrounded_load():
    # 3.94 h vs 4.0 h both round to 0.5 days; the larger load must still rank first.
    d = data(
        [product(1, "A"), product(2, "B")],
        [bom(1, 1, {2: 1}, ops=[(5, 47.3)]), bom(2, 2, {}, ops=[(6, 48)])],
        [work_center(5, "W1"), work_center(6, "W2")],
    )
    assert [c.code for c in plan(d, 1, 5).capacity] == ["W2", "W1"]
