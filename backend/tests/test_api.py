import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.odoo import get_odoo_client
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


def test_health_ok(api):
    assert api.get("/api/health").json() == {
        "status": "ok",
        "odoo": {"mode": "fake", "reachable": True, "version": "20.0+e", "error": None},
    }


def test_health_degraded_when_odoo_down(api, fake):
    fake.fail = True
    resp = api.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "degraded"
    assert resp.json()["odoo"]["reachable"] is False


def test_odoo_failure_maps_to_502(api, fake):
    fake.fail = True
    resp = api.get("/api/dashboard/low-stock")
    assert resp.status_code == 502
    assert resp.json()["error"] == "odoo_error"


def test_summary(api):
    assert api.get("/api/dashboard/summary").json() == {
        "currency": "HKD",
        "open_sales_count": 2,
        "open_sales_value": 2500.0,
        "quotations_count": 1,
        "manufacturing_by_state": {"done": 1, "progress": 1, "confirmed": 2},
        "active_manufacturing_count": 3,
        "low_stock_count": 2,
    }


def test_sales_orders_returns_only_open(api):
    assert [o["id"] for o in api.get("/api/dashboard/sales-orders").json()] == [1, 2]


def test_low_stock_returns_most_critical_first(api):
    assert [s["product_code"] for s in api.get("/api/dashboard/low-stock").json()] == ["LCD-35", "CHP-MCU"]


def test_orders_over_time_validates_weeks(api):
    assert api.get("/api/dashboard/orders-over-time?weeks=0").status_code == 422
    assert len(api.get("/api/dashboard/orders-over-time?weeks=8").json()) == 8
