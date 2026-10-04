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
