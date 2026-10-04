"""Read-only dashboard endpoints. Each one is a thin shell: fetch via the
OdooClient, apply a rule from services.dashboard, return a typed response."""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.odoo import OdooClient, get_odoo_client
from app.schemas.dashboard import DashboardSummary, WeeklyOrders
from app.schemas.erp import ManufacturingOrder, SaleOrder, StockLevel
from app.services import dashboard as rules

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])

Odoo = Annotated[OdooClient, Depends(get_odoo_client)]


def _today():
    return datetime.now(UTC).date()


@router.get("/summary", response_model=DashboardSummary)
def summary(odoo: Odoo) -> DashboardSummary:
    open_orders = rules.open_sale_orders(odoo.list_sale_orders())
    mos = odoo.list_manufacturing_orders()
    return DashboardSummary(
        currency=odoo.company_currency(),
        open_sales_count=len(open_orders),
        open_sales_value=sum(o.amount_total for o in open_orders),
        quotations_count=sum(o.state in rules.QUOTATION_STATES for o in open_orders),
        manufacturing_by_state=rules.manufacturing_state_counts(mos),
        active_manufacturing_count=len(rules.active_manufacturing_orders(mos)),
        low_stock_count=len(rules.low_stock(odoo.list_stock_levels())),
    )


@router.get("/sales-orders", response_model=list[SaleOrder])
def open_sales_orders(odoo: Odoo) -> list[SaleOrder]:
    return rules.open_sale_orders(odoo.list_sale_orders())


@router.get("/manufacturing-orders", response_model=list[ManufacturingOrder])
def manufacturing_orders(odoo: Odoo) -> list[ManufacturingOrder]:
    return odoo.list_manufacturing_orders()


@router.get("/low-stock", response_model=list[StockLevel])
def low_stock(odoo: Odoo) -> list[StockLevel]:
    return rules.low_stock(odoo.list_stock_levels())


@router.get("/orders-over-time", response_model=list[WeeklyOrders])
def orders_over_time(odoo: Odoo, weeks: Annotated[int, Query(ge=1, le=52)] = 12) -> list[WeeklyOrders]:
    today = _today()
    orders = odoo.list_sale_orders(since=rules.orders_window_start(weeks=weeks, today=today))
    return rules.orders_over_time(orders, weeks=weeks, today=today)
