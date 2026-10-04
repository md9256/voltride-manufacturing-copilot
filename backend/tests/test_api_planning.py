import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.odoo import get_odoo_client
from tests.factories import CHIP, CTL, KIT, LCD, bom
from tests.fakes import FakeOdooClient


@pytest.fixture
def fake():
    client = FakeOdooClient()
    app.dependency_overrides[get_odoo_client] = lambda: client
    yield client
    app.dependency_overrides.clear()


@pytest.fixture
def api(fake):
    return TestClient(app)


def test_products_filtered_by_kind(api):
    made = api.get("/api/products?kind=manufactured").json()
    assert [p["code"] for p in made] == ["CTL", "DSP", "KIT"]
    assert all(p["unit_cost"] > 0 for p in made)
    assert api.get("/api/products?kind=nonsense").status_code == 422


def test_bom_tree_has_statuses_and_quantities(api):
    tree = api.get(f"/api/bom/{KIT}/tree?quantity=2").json()
    assert tree["code"] == "KIT"
    assert tree["status"] == "short"  # 4 chips needed, 3 free, no incoming
    ctl = next(c for c in tree["children"] if c["product_id"] == CTL)
    chip = next(c for c in ctl["children"] if c["product_id"] == CHIP)
    assert (chip["qty_per_unit"], chip["quantity"], chip["status"], chip["level"]) == (1, 2, "short", 2)


def test_bom_tree_errors(api):
    assert api.get("/api/bom/9999/tree").status_code == 404
    resp = api.get(f"/api/bom/{LCD}/tree")
    assert resp.status_code == 422
    assert "purchased" in resp.json()["detail"]
    assert api.get(f"/api/bom/{KIT}/tree?quantity=0").status_code == 422


def test_plan_endpoint(api):
    resp = api.post("/api/planner/plan", json={"product_id": KIT, "quantity": 5, "count_incoming": False})
    assert resp.status_code == 200
    body = resp.json()
    assert body["product"]["code"] == "KIT"
    assert body["purchase_total"] == 420
    assert body["material_bottlenecks"][0]["code"] == "CHIP"
    assert body["capacity_bottleneck"]["code"] in {"ASM", "TST"}


@pytest.mark.parametrize(
    "payload",
    [
        {"product_id": KIT, "quantity": 0},
        {"product_id": KIT, "quantity": 10_001},
        {"product_id": KIT, "quantity": "lots"},
        {"quantity": 5},
    ],
)
def test_plan_validates_input(api, payload):
    assert api.post("/api/planner/plan", json=payload).status_code == 422


def test_plan_unknown_product_is_404(api):
    assert api.post("/api/planner/plan", json={"product_id": 9999, "quantity": 1}).status_code == 404


def test_bom_cycle_is_422_with_path(api, fake):
    fake.boms = [*fake.boms, bom(99, CHIP, {KIT: 1})]  # chip now "contains" the kit
    resp = api.post("/api/planner/plan", json={"product_id": KIT, "quantity": 1})
    assert resp.status_code == 422
    assert resp.json()["error"] == "bom_cycle"
    assert "KIT -> CTL -> CHIP -> KIT" in resp.json()["detail"]
