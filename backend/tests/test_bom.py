import pytest

from app.services.bom import BomCycleError, BomError, UnknownProductError, explode, low_level_codes, unit_costs
from tests.factories import CHIP, CTL, DSP, KIT, bom, data, mini_voltride, product, work_center


def flatten(node, depth=0):
    out = [(depth, node.product_id, node.qty_per_unit, node.quantity)]
    for child in node.children:
        out += flatten(child, depth + 1)
    return out


def test_explode_multiplies_quantities_through_levels():
    # A needs 2 B; each B needs 3 C  ->  building 5 A needs 10 B and 30 C.
    d = data([product(1, "A"), product(2, "B"), product(3, "C")], [bom(1, 1, {2: 2}), bom(2, 2, {3: 3})])
    assert flatten(explode(d, 1, 5)) == [(0, 1, 1, 5), (1, 2, 2, 10), (2, 3, 6, 30)]


def test_explode_scales_batch_boms():
    # The B recipe makes 10 B from 5 C, i.e. 0.5 C per B.
    d = data([product(1, "A"), product(2, "B"), product(3, "C")], [bom(1, 1, {2: 4}), bom(2, 2, {3: 5}, qty=10)])
    tree = explode(d, 1, 1)
    assert tree.children[0].children[0].quantity == pytest.approx(2.0)


def test_purchased_products_are_leaves():
    tree = explode(mini_voltride(), KIT, 1)
    leaves = [n for n in flatten(tree) if n[1] in (CHIP,)]
    assert len(leaves) == 2  # the chip appears under both the controller and the display


def test_cycle_is_detected_with_its_path():
    d = data(
        [product(1, "A"), product(2, "B"), product(3, "C")], [bom(1, 1, {2: 1}), bom(2, 2, {3: 1}), bom(3, 3, {1: 1})]
    )
    with pytest.raises(BomCycleError) as exc:
        explode(d, 1, 1)
    assert exc.value.path == ["A", "B", "C", "A"]


def test_self_referencing_bom_is_a_cycle():
    d = data([product(1, "A")], [bom(1, 1, {1: 1})])
    with pytest.raises(BomCycleError, match="A -> A"):
        explode(d, 1, 1)


def test_shared_component_is_not_a_cycle():
    # A diamond (KIT -> CTL -> CHIP and KIT -> DSP -> CHIP) is fine.
    explode(mini_voltride(), KIT, 1)


def test_unknown_root_and_dangling_line():
    d = data([product(1, "A")], [bom(1, 1, {99: 1})])
    with pytest.raises(UnknownProductError):
        explode(d, 42, 1)
    with pytest.raises(BomError, match="unknown product 99"):
        explode(d, 1, 1)


def test_lowest_sequence_bom_wins():
    d = data(
        [product(1, "A"), product(2, "B"), product(3, "C")],
        [bom(1, 1, {2: 1}, sequence=5), bom(2, 1, {3: 1}, sequence=1)],
    )
    assert explode(d, 1, 1).children[0].product_id == 3


def test_low_level_code_is_deepest_occurrence():
    # C sits at level 1 under A and at level 2 under B; its low-level code is 2.
    d = data([product(1, "A"), product(2, "B"), product(3, "C")], [bom(1, 1, {2: 1, 3: 1}), bom(2, 2, {3: 1})])
    assert low_level_codes(explode(d, 1, 1)) == {1: 0, 2: 1, 3: 2}


def test_unit_cost_rolls_up_material_and_labour():
    d = data(
        [product(1, "A"), product(2, "B", cost=10), product(3, "C", cost=4)],
        [bom(1, 1, {2: 2, 3: 5}, qty=2, ops=[(7, 30)])],  # batch of 2 A
        [work_center(7, "W", rate=60, efficiency=0.5)],
    )
    # material per A: (2*10 + 5*4) / 2 = 20; labour: 30 min at 50 % efficiency = 1 h * 60
    assert unit_costs(d, {1})[1] == pytest.approx(80)


def test_mini_voltride_costs():
    costs = unit_costs(mini_voltride(), {KIT, CTL, DSP})
    assert costs[CTL] == pytest.approx(60 + 140 + 12 / 60 * 60 + 20 / 60 * 30)
    assert costs[DSP] == pytest.approx(60 + 160 + 6 / 60 * 30)
    assert costs[KIT] == pytest.approx(costs[CTL] + costs[DSP] + 20 + 30 / 60 * 60)
