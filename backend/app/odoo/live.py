"""Live OdooClient: maps Odoo JSON-2 results onto our ERP records.

Field names here were verified against the live Odoo 20 instance with
fields_get (see scripts/check_odoo.py), not assumed from older versions.
"""

from datetime import UTC, datetime
from typing import Any

from app.odoo.base import OdooClient
from app.odoo.rpc import OdooRpc
from app.schemas.erp import ManufacturingOrder, SaleOrder, StockLevel

ODOO_DT = "%Y-%m-%d %H:%M:%S"


class LiveOdooClient(OdooClient):
    mode = "live"

    def __init__(self, rpc: OdooRpc) -> None:
        self._rpc = rpc

    def server_version(self) -> str:
        # context_get is the cheapest authenticated call; it proves the key works.
        self._rpc.call("res.users", "context_get")
        return self._rpc.server_version()

    def company_currency(self) -> str:
        company = self._rpc.search_read("res.company", [], ["currency_id"], limit=1)
        return _m2o_name(company[0]["currency_id"]) or ""

    def list_sale_orders(self, since: datetime | None = None) -> list[SaleOrder]:
        domain = [["date_order", ">=", since.astimezone(UTC).strftime(ODOO_DT)]] if since else []
        rows = self._rpc.search_read(
            "sale.order",
            domain,
            ["name", "partner_id", "state", "delivery_status", "date_order", "commitment_date", "amount_total"],
            order="date_order desc",
        )
        return [
            SaleOrder(
                id=r["id"],
                name=r["name"],
                customer=_m2o_name(r["partner_id"]) or "",
                state=r["state"],
                delivery_status=r["delivery_status"] or None,
                date_order=_dt(r["date_order"]),
                commitment_date=_dt(r["commitment_date"]),
                amount_total=r["amount_total"],
            )
            for r in rows
        ]

    def list_manufacturing_orders(self) -> list[ManufacturingOrder]:
        rows = self._rpc.search_read(
            "mrp.production",
            [],
            ["name", "product_id", "product_qty", "state", "date_start", "date_finished", "origin"],
            order="date_start desc",
        )
        products = self._product_codes({r["product_id"][0] for r in rows})
        return [
            ManufacturingOrder(
                id=r["id"],
                name=r["name"],
                product_code=products[r["product_id"][0]][0],
                product_name=products[r["product_id"][0]][1],
                quantity=r["product_qty"],
                state=r["state"],
                date_start=_dt(r["date_start"]),
                date_finished=_dt(r["date_finished"]),
                origin=r["origin"] or None,
            )
            for r in rows
        ]

    def list_stock_levels(self) -> list[StockLevel]:
        rows = self._rpc.search_read(
            "stock.warehouse.orderpoint",
            [],
            ["product_id", "qty_on_hand", "product_min_qty", "product_max_qty"],
        )
        products = self._product_codes({r["product_id"][0] for r in rows})
        return [
            StockLevel(
                product_id=r["product_id"][0],
                product_code=products[r["product_id"][0]][0],
                product_name=products[r["product_id"][0]][1],
                on_hand=r["qty_on_hand"],
                min_qty=r["product_min_qty"],
                max_qty=r["product_max_qty"],
            )
            for r in rows
        ]

    def _product_codes(self, ids: set[int]) -> dict[int, tuple[str | None, str]]:
        """product id -> (internal reference, plain name).

        many2one display names look like "[MTR-750] High-power motor 750W";
        we read the two parts separately instead of parsing that string.
        """
        if not ids:
            return {}
        rows = self._rpc.call("product.product", "read", ids=sorted(ids), fields=["default_code", "name"])
        return {r["id"]: (r["default_code"] or None, r["name"]) for r in rows}


def _m2o_name(value: Any) -> str | None:
    """Odoo many2one values are `[id, display_name]`, or False when empty."""
    return value[1] if value else None


def _dt(value: str | bool) -> datetime | None:
    """Odoo datetimes are naive UTC strings, or False when empty.

    We attach UTC explicitly so the API emits "+00:00" and browsers convert to
    local time instead of guessing.
    """
    return datetime.strptime(value, ODOO_DT).replace(tzinfo=UTC) if value else None
