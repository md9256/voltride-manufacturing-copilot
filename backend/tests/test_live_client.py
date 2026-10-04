import json
from datetime import UTC, datetime

import httpx

from app.odoo.live import LiveOdooClient
from app.odoo.rpc import OdooRpc


def client_with(routes: dict) -> LiveOdooClient:
    """routes maps "model/method" to a JSON response, or to a callable(body) returning one."""

    def handler(request: httpx.Request) -> httpx.Response:
        result = routes[request.url.path.removeprefix("/json/2/")]
        return httpx.Response(200, json=result(json.loads(request.content)) if callable(result) else result)

    return LiveOdooClient(OdooRpc("https://odoo.test", "db", "k", transport=httpx.MockTransport(handler)))


def test_sale_orders_map_odoo_fields():
    client = client_with(
        {
            "sale.order/search_read": [
                {
                    "id": 1,
                    "name": "S00001",
                    "partner_id": [5, "Alpine Cycles GmbH"],
                    "state": "sale",
                    "delivery_status": False,
                    "date_order": "2026-09-01 09:00:00",
                    "commitment_date": False,
                    "amount_total": 23200.0,
                }
            ]
        }
    )

    [order] = client.list_sale_orders()

    assert order.customer == "Alpine Cycles GmbH"
    assert order.delivery_status is None  # Odoo's False becomes None
    assert order.commitment_date is None
    assert order.date_order == datetime(2026, 9, 1, 9, tzinfo=UTC)


def test_sale_orders_since_sends_utc_domain():
    seen = {}

    def search_read(body):
        seen.update(body)
        return []

    client_with({"sale.order/search_read": search_read}).list_sale_orders(since=datetime(2026, 9, 1, 17, tzinfo=UTC))
    assert seen["domain"] == [["date_order", ">=", "2026-09-01 17:00:00"]]


def test_stock_levels_read_code_and_name_separately():
    client = client_with(
        {
            "stock.warehouse.orderpoint/search_read": [
                {
                    "id": 1,
                    "product_id": [5, "[CHP-MCU] MCU chip STM32G4"],
                    "qty_on_hand": 3.0,
                    "product_min_qty": 40.0,
                    "product_max_qty": 150.0,
                }
            ],
            "product.product/read": [{"id": 5, "default_code": "CHP-MCU", "name": "MCU chip STM32G4"}],
        }
    )

    [level] = client.list_stock_levels()

    assert (level.product_code, level.product_name, level.on_hand, level.min_qty) == (
        "CHP-MCU",
        "MCU chip STM32G4",
        3.0,
        40.0,
    )


def test_work_orders_rebuild_planned_minutes_for_finished_ones():
    def wo(id, state, expected, duration, start, end):
        return {
            "id": id,
            "name": "Solder",
            "production_id": [4, "WH/MO/00004"],
            "product_id": [5, "[SA] x"],
            "qty_production": 10.0,
            "workcenter_id": [1, "PCB Line"],
            "state": state,
            "date_start": start,
            "date_finished": end,
            "duration_expected": expected,
            "duration": duration,
            "operation_id": [7, "Solder"],
        }

    client = client_with(
        {
            "mrp.workorder/search_read": [
                # Odoo rewrote the finished order's expected duration to 0.
                wo(1, "done", 0.0, 130.0, "2026-09-14 08:00:00", "2026-09-14 10:10:00"),
                wo(2, "ready", 120.0, 0.0, "2026-10-05 00:00:00", "2026-10-05 02:00:00"),
            ],
            "mrp.routing.workcenter/read": [{"id": 7, "time_cycle_manual": 12.0}],
            "mrp.workcenter/read": [{"id": 1, "time_efficiency": 80.0, "time_start": 5.0, "time_stop": 5.0}],
            "product.product/read": [{"id": 5, "default_code": "SA-CTL", "name": "Controller"}],
        }
    )

    done, ready = client.list_work_orders()

    assert done.planned_minutes == 160.0  # 5 + 5 + 12 min x 10 / 80 %
    assert (done.actual_minutes, done.is_actual) == (130.0, True)
    assert (ready.planned_minutes, ready.is_actual) == (120.0, False)  # Odoo's own plan, untouched
    assert ready.date_start == datetime(2026, 10, 5, 0, 0, tzinfo=UTC)
