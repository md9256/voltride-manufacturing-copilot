import json

import pytest

from app.ai.tools import TOOLS, ToolContext, ToolError, ToolRunner, resolve_product
from app.odoo import OdooError
from tests.factories import CHIP, CTL
from tests.fakes import FakeOdooClient


@pytest.fixture
def fake():
    return FakeOdooClient()


@pytest.fixture
def runner(fake):
    return ToolRunner(ToolContext(fake))


def run_ok(runner, name, args):
    outcome = runner.run(name, args)
    assert outcome.ok, outcome.content
    return json.loads(outcome.content)


def run_err(runner, name, args) -> str:
    outcome = runner.run(name, args)
    assert not outcome.ok
    return json.loads(outcome.content)["error"]


def test_every_tool_schema_forbids_unknown_arguments():
    for tool in TOOLS:
        schema = tool.json_schema()
        assert schema["type"] == "object"
        assert schema["additionalProperties"] is False, tool.name


def test_tool_names_are_unique_and_described():
    names = [t.name for t in TOOLS]
    assert len(names) == len(set(names))
    assert all(len(t.description) > 20 for t in TOOLS)


@pytest.mark.parametrize("ref", ["CHIP", "chip", "CHIP name", "chip NAME"])
def test_resolve_product_by_code_or_name(fake, ref):
    assert resolve_product(ToolContext(fake).data, ref).id == CHIP


def test_resolve_product_ambiguous_lists_candidates(fake):
    with pytest.raises(ToolError, match="several products") as exc:
        resolve_product(ToolContext(fake).data, "name")  # every fixture name contains it
    assert "Use an exact product code" in str(exc.value)


def test_resolve_product_unknown_suggests(fake):
    with pytest.raises(ToolError, match="Did you mean: CHIP"):
        resolve_product(ToolContext(fake).data, "CHPI")


def test_validation_rejects_bad_arguments_before_running(runner):
    assert "quantity" in run_err(runner, "get_bom_shortages", {"product": "KIT", "quantity": -1})
    assert "quantity" in run_err(runner, "get_bom_shortages", {"product": "KIT", "quantity": 50_000})
    assert "Extra inputs" in run_err(runner, "get_bom_shortages", {"product": "KIT", "quantity": 1, "rm": "-rf"})
    assert "product" in run_err(runner, "get_bom_shortages", {"quantity": 1})


def test_non_object_arguments_and_unknown_tool(runner):
    assert "JSON object" in run_err(runner, "get_bom_shortages", "not json")
    assert "Unknown tool" in run_err(runner, "drop_database", {})


def test_bom_shortages_reports_short_components(runner):
    result = run_ok(runner, "get_bom_shortages", {"product": "KIT", "quantity": 2, "count_incoming": False})
    assert result["can_build_from_stock"] is False
    [chip] = result["short_components"]
    assert (chip["code"], chip["needed"], chip["short"], chip["supplier"], chip["lead_days"]) == (
        "CHIP",
        4,
        1,
        "ChipCo",
        35,
    )
    assert {s["code"] for s in result["subassemblies_to_build"]} == {"CTL", "DSP"}
    assert result["currency"] == "HKD"


def test_bom_shortages_rejects_purchased_product(runner):
    assert "purchased" in run_err(runner, "get_bom_shortages", {"product": "CHIP", "quantity": 1})


def test_get_bom_depth(runner):
    shallow = run_ok(runner, "get_bom", {"product": "KIT"})
    ctl = next(c for c in shallow["components"] if c["code"] == "CTL")
    assert "components" not in ctl and ctl["components_not_shown"] == 2
    deep = run_ok(runner, "get_bom", {"product": "KIT", "levels": 2})
    ctl = next(c for c in deep["components"] if c["code"] == "CTL")
    assert {c["code"] for c in ctl["components"]} == {"CHIP", "PCB"}


def test_search_products_filters(runner):
    result = run_ok(runner, "search_products", {"query": "name", "kind": "manufactured"})
    assert [p["code"] for p in result["products"]] == ["CTL", "DSP", "KIT"]


def test_stock_levels_for_named_products(runner):
    result = run_ok(runner, "get_stock_levels", {"products": ["chip", "PCB"]})
    assert [p["code"] for p in result["products"]] == ["CHIP", "PCB"]
    assert result["products"][0]["free"] == 3


def test_stock_levels_unknown_product_is_recoverable_error(runner):
    assert "No product matches 'XYZ-999'" in run_err(runner, "get_stock_levels", {"products": ["XYZ-999"]})


@pytest.mark.parametrize("ref", ["WH/MO/00002", "wh/mo/00002", "00002", "2"])
def test_manufacturing_order_reference_forms(runner, ref):
    assert run_ok(runner, "get_manufacturing_order", {"reference": ref})["reference"] == "WH/MO/00002"


def test_manufacturing_order_not_found_lists_known(runner):
    assert "WH/MO/00001" in run_err(runner, "get_manufacturing_order", {"reference": "99"})


def test_list_manufacturing_orders_by_state(runner):
    result = run_ok(runner, "list_manufacturing_orders", {"states": ["confirmed"]})
    assert [o["reference"] for o in result["orders"]] == ["WH/MO/00003", "WH/MO/00004"]
    assert result["count_by_state"] == {"done": 1, "progress": 1, "confirmed": 2}


def test_sales_summary(runner):
    result = run_ok(runner, "get_sales_summary", {"weeks": 4})
    assert result["open_orders"] == {"count": 2, "value": 2500.0, "quotations": 1}
    assert len(result["weekly_confirmed"]) == 4


def test_odoo_failure_becomes_generic_error_result(fake, runner):
    fake.fail = True
    message = run_err(runner, "get_stock_levels", {})
    assert "could not be reached" in message
    assert "503" not in message  # no backend details leaked to the model


def test_catalogue_fetched_once_per_turn(fake):
    calls = []
    original = fake.list_products
    fake.list_products = lambda: calls.append(1) or original()
    runner = ToolRunner(ToolContext(fake))
    runner.run("get_bom", {"product": "KIT"})
    runner.run("get_bom_shortages", {"product": "KIT", "quantity": 1})
    assert len(calls) == 1


def test_tool_result_is_json_and_keeps_non_ascii(runner, fake):
    fake.products = [p.model_copy(update={"name": "控制器"}) if p.id == CTL else p for p in fake.products]
    outcome = ToolRunner(ToolContext(fake)).run("search_products", {"query": "控制器"})
    assert "控制器" in outcome.content  # not \\u-escaped: fewer tokens, readable
    assert json.loads(outcome.content)["products"][0]["code"] == "CTL"


def test_unexpected_odoo_errors_do_not_escape(fake, runner, monkeypatch):
    monkeypatch.setattr(fake, "list_manufacturing_orders", lambda: (_ for _ in ()).throw(OdooError("boom")))
    assert not runner.run("list_manufacturing_orders", {}).ok
